#!/usr/bin/env bash
# Launch headed Chrome with the HNA profile and attach agent-browser via CDP.
# Why a manual launch instead of `agent-browser --headed --profile`:
#   - The agent-browser daemon silently ignores --headed/--profile if a daemon
#     is already running, and on this machine the headed window also crashed and
#     got respawned headless. Launching Chrome ourselves on a fixed CDP port and
#     attaching with `--cdp` sidesteps both problems and is reliable.
#
# Exit codes:
#   0  = logged in, parked on the leave-application form
#   10 = NOT logged in (caller must ask the user to log in, then re-run)
set -euo pipefail

PROFILE="$HOME/.agent-browser/profiles/hna"
PORT="${HNA_CDP_PORT:-9222}"
TARGET="http://hr.hna.net/ehr/NewHomePage/EmployeeBenefits/LeaveApplicationLink.aspx"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Reuse an existing CDP session if one is already up, otherwise launch fresh.
if ! curl -s "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  pkill -f "remote-debugging-port=${PORT}" 2>/dev/null || true
  sleep 1
  rm -f "$PROFILE"/Singleton* 2>/dev/null || true
  # --disable-popup-blocking is essential: the 固化流程 button opens its flow
  # picker via window.open(), and Chrome's popup blocker intermittently swallows
  # window.open calls driven by CDP clicks. Disabling the blocker keeps the
  # popup (and its window.opener link back to the form) working every time.
  nohup "$CHROME" \
    --user-data-dir="$PROFILE" \
    --remote-debugging-port="${PORT}" \
    --no-first-run --no-default-browser-check \
    --disable-popup-blocking \
    --window-size=1400,900 \
    "$TARGET" >/tmp/hna-chrome.log 2>&1 &
  # Wait for CDP to come up.
  for _ in $(seq 1 20); do
    curl -s "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1 && break
    sleep 1
  done
fi

ab() { agent-browser --cdp "${PORT}" "$@"; }

ab open "$TARGET" >/dev/null 2>&1 || true

# When the SSO cookie is still valid the login page auto-bounces
# (login.hnagroup.com → ssocallback → form with a fresh machinekey). That
# round-trip takes a few seconds, so poll instead of checking once.
for _ in $(seq 1 15); do
  URL="$(ab get url 2>/dev/null || echo '')"
  case "$URL" in
    *hr.hna.net*LeaveApplicationLink*)
      echo "READY"
      exit 0
      ;;
  esac
  sleep 1
done

# Still not on the form after ~15s. If the password form is actually showing,
# the user genuinely needs to log in; otherwise report whatever we landed on.
URL="$(ab get url 2>/dev/null || echo '')"
case "$URL" in
  *login.hnagroup.com*|*ssocallback*)
    echo "NOT_LOGGED_IN"
    exit 10
    ;;
  *)
    echo "UNKNOWN: $URL"
    exit 11
    ;;
esac
