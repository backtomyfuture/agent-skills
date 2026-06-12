#!/usr/bin/env bash
# Launch Chrome with the HNA profile and attach agent-browser via CDP.
# Why a manual launch instead of `agent-browser --headed --profile`:
#   - The agent-browser daemon silently ignores --headed/--profile if a daemon
#     is already running, and on this machine the headed window also crashed and
#     got respawned headless. Launching Chrome ourselves on a fixed CDP port and
#     attaching with `--cdp` sidesteps both problems and is reliable.
#
# Headless by default: the whole flow is driven via CDP + in-page JS, which
# behaves identically under --headless=new, and with no visible window there is
# nothing for the user to accidentally close or lose. The ONE thing that needs
# a visible window is manual SSO login — so when we detect NOT_LOGGED_IN from a
# headless instance, we swap it for a headed one parked on the login page.
# Set HNA_HEADED=1 to force a visible window for the whole run (debugging).
#
# Login persistence: the HNA SSO cookies are *session* cookies, so the Chrome
# profile dir alone forgets the login whenever Chrome exits. We therefore keep
# a state.json (cookies + storage, saved via `agent-browser state save`) inside
# the hna profile: load it before navigating, and re-save it on every
# successful logged-in run. After a manual login, just re-run this script —
# it will land on the form and capture the fresh state automatically.
#
# Exit codes:
#   0  = logged in, parked on the leave-application form (state.json refreshed)
#   10 = NOT logged in (a headed window is now showing the login page; ask the
#        user to log in there, then re-run)
set -euo pipefail

PROFILE="$HOME/.agent-browser/profiles/hna"
STATE="$PROFILE/state.json"
PORT="${HNA_CDP_PORT:-9222}"
TARGET="http://hr.hna.net/ehr/NewHomePage/EmployeeBenefits/LeaveApplicationLink.aspx"
# The 固化流程 picker lives on oa3.hnair.net behind its own CAS auth, which in
# turn needs a live SSO master session at login.hnagroup.com. The hr.hna.net
# form can open from its own app cookies even after that SSO session has
# idle-expired — so reaching the form is NOT enough; we probe oa3 explicitly.
OA3_PROBE="http://oa3.hnair.net/OAWebApp/OA/Workflow/Process/MyFlow.aspx?Advice=2"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

MODE="headless"
[ "${HNA_HEADED:-0}" = "1" ] && MODE="headed"

# launch_chrome <headless|headed> [url] — kill any instance on our port and
# start fresh, opening the given URL (default: the leave form).
launch_chrome() {
  pkill -f "remote-debugging-port=${PORT}" 2>/dev/null || true
  sleep 1
  rm -f "$PROFILE"/Singleton* 2>/dev/null || true
  local extra=()
  [ "$1" = "headless" ] && extra+=(--headless=new)
  # --disable-popup-blocking is essential: the 固化流程 button opens its flow
  # picker via window.open(), and Chrome's popup blocker intermittently swallows
  # window.open calls driven by CDP clicks. Disabling the blocker keeps the
  # popup (and its window.opener link back to the form) working every time.
  nohup "$CHROME" \
    ${extra[@]+"${extra[@]}"} \
    --user-data-dir="$PROFILE" \
    --remote-debugging-port="${PORT}" \
    --no-first-run --no-default-browser-check \
    --disable-popup-blocking \
    --window-size=1400,900 \
    "${2:-$TARGET}" >/tmp/hna-chrome.log 2>&1 &
  for _ in $(seq 1 20); do
    curl -s "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "ERROR: Chrome CDP did not come up on port ${PORT}" >&2
  exit 1
}

# Reuse an existing CDP session if one is already up (whatever mode it's in —
# e.g. the headed window the user just logged in through), otherwise launch.
if ! curl -s "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  launch_chrome "$MODE"
fi

ab() { agent-browser --cdp "${PORT}" "$@"; }

# Re-inject the saved login cookies before navigating, so an expired
# in-browser session still auto-logs-in from the last saved state.
if [ -f "$STATE" ]; then
  ab state load "$STATE" >/dev/null 2>&1 || true
fi

ab open "$TARGET" >/dev/null 2>&1 || true

# When the SSO cookie is still valid the login page auto-bounces
# (login.hnagroup.com → ssocallback → form with a fresh machinekey). That
# round-trip takes a few seconds, so poll instead of checking once.
for _ in $(seq 1 15); do
  URL="$(ab get url 2>/dev/null || echo '')"
  case "$URL" in
    *hr.hna.net*LeaveApplicationLink*)
      # Form reachable. Now probe the oa3 SSO session in a separate tab — the
      # 固化流程 popup would bounce to the SSO login page if it has idle-expired,
      # even though the form itself opened fine from hr.hna.net's own cookies.
      MAIN_ID="$(ab tab 2>/dev/null | grep LeaveApplicationLink | grep -oE '\bt[0-9]+\b' | head -1)"
      ab tab new >/dev/null 2>&1 || true
      ab open "$OA3_PROBE" >/dev/null 2>&1 || true
      PROBE_URL=""
      for _ in $(seq 1 15); do
        PROBE_URL="$(ab get url 2>/dev/null || echo '')"
        case "$PROBE_URL" in *oa3.hnair.net*MyFlow*) break ;; esac
        sleep 1
      done
      case "$PROBE_URL" in
        *oa3.hnair.net*MyFlow*)
          # SSO alive. Save state NOW so it also captures oa3's own session
          # cookies (they let the popup work from a cold start, the same way
          # hr.hna.net's cookies open the form), then park back on the form.
          ab tab close >/dev/null 2>&1 || true
          { [ -n "$MAIN_ID" ] && ab tab "$MAIN_ID" >/dev/null 2>&1; } || true
          ab state save "$STATE" >/dev/null 2>&1 || true
          echo "READY"
          exit 0
          ;;
        *login.hnagroup.com*|*ssocallback*)
          # SSO master session expired: the user must log in by hand, which
          # needs a visible window parked on the SSO login page (the probe URL
          # bounces there). After they log in, re-run this script.
          if curl -s "http://127.0.0.1:${PORT}/json/version" | grep -q "HeadlessChrome"; then
            launch_chrome headed "$OA3_PROBE"
          fi
          echo "NOT_LOGGED_IN"
          exit 10
          ;;
        *)
          echo "UNKNOWN: oa3 SSO probe landed on: $PROBE_URL"
          exit 11
          ;;
      esac
      ;;
  esac
  sleep 1
done

# Still not on the form after ~15s. If the password form is actually showing,
# the user genuinely needs to log in; otherwise report whatever we landed on.
URL="$(ab get url 2>/dev/null || echo '')"
case "$URL" in
  *login.hnagroup.com*|*ssocallback*)
    # The user has to type their password, so they need a window they can see.
    # If the current instance is headless, swap it for a headed one parked on
    # the login page (TARGET bounces there) before reporting NOT_LOGGED_IN.
    # Headless detection: ask the browser itself — a headless instance reports
    # "HeadlessChrome" in CDP /json/version (ps-grepping for --headless is
    # fragile: helper processes and the grep pipeline itself self-match).
    if curl -s "http://127.0.0.1:${PORT}/json/version" | grep -q "HeadlessChrome"; then
      launch_chrome headed
    fi
    echo "NOT_LOGGED_IN"
    exit 10
    ;;
  *)
    echo "UNKNOWN: $URL"
    exit 11
    ;;
esac
