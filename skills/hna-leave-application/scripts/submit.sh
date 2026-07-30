#!/usr/bin/env bash
# Submit the leave application and verify it actually reached the server.
# Run it after fill_form.sh + a screenshot sanity check. Submission must be
# explicitly requested by the user; the guards below prevent double firing and
# false success reports, but do not replace that authorization.
#
# The 提交 <button> carries onclick="checkFormMain()". A CDP/ref click does NOT
# reliably fire that handler (same gotcha as the 固化流程 button), so we invoke
# checkFormMain() directly in page context — it is exactly what the button does:
# validates via checkForm(), then POSTs to /EHR/Handler/LeaveApplication.ashx
# (action=savemyapply) and, on success, shows "提交成功…" and redirects to the
# 公文跟踪 page.
#
# We confirm success from at least one live proof: the savemyapply POST, the
# success toast, or the expected navigation. Network logs can be tab-scoped and
# may no longer be visible after a redirect, so a later empty log is not proof
# that the submission failed.
set -euo pipefail

PORT="${HNA_CDP_PORT:-9222}"
ab() { agent-browser --cdp "${PORT}" "$@"; }

# The HNA browser is launched manually by launch.sh and agent-browser merely
# attaches through CDP. `agent-browser close` therefore does not reliably
# stop this browser, and can instead affect an unrelated default session.
# Close only the Chrome process tree that owns this skill's fixed CDP port.
close_hna_automation() {
  local pattern="remote-debugging-port=${PORT}"
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    pkill -f "$pattern" >/dev/null 2>&1 || return 1
  fi
  for _ in $(seq 1 20); do
    curl -s --max-time 1 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1 || return 0
    sleep 0.2
  done
  return 1
}

# agent-browser acts on the active tab. Never invoke checkFormMain() from an
# unrelated oa3 page such as 公文跟踪: locate and activate the actual HR form
# first, otherwise a pre-existing tracking URL could be mistaken for a success
# redirect.
FORM_ID="$(ab tab 2>/dev/null | grep LeaveApplicationLink | grep -oE '\bt[0-9]+\b' | head -1 || true)"
if [ -z "$FORM_ID" ]; then
  echo "ERROR: leave-application form tab not found; run fill_form.sh first" >&2
  exit 1
fi
if ! ab tab "$FORM_ID" >/dev/null 2>&1; then
  echo "ERROR: could not activate the leave-application form tab" >&2
  exit 1
fi
FORM_URL="$(ab get url 2>/dev/null || echo '')"
case "$FORM_URL" in
  *LeaveApplicationLink.aspx*) ;;
  *)
    echo "ERROR: active tab is not the leave-application form: $FORM_URL" >&2
    exit 1
    ;;
esac

# Clear any stale layer toast left over from a previous attempt.
ab eval "if(typeof layer!=='undefined'&&layer.closeAll){layer.closeAll();}'cleared'" >/dev/null 2>&1 || true

# Guard against double-submit: if a savemyapply POST already went out, stop.
if ab network requests 2>/dev/null | grep -q "savemyapply"; then
  echo "ALREADY_SUBMITTED: a savemyapply request is already in the network log" >&2
  exit 3
fi

# Do not call checkForm() as a standalone preview. On the current portal it
# shows a submission-style overlay, and checkFormMain() already invokes the
# same validation immediately before its one real POST.
# Fire the real submit exactly once.
ab eval "checkFormMain(); 'submitting'" >/dev/null 2>&1 || true

# Wait for proof of success: either the savemyapply POST appears, the page
# navigates to 公文跟踪, or the success toast shows.
ok=""
for i in $(seq 1 30); do
  sleep 1
  if ab network requests 2>/dev/null | grep -q "savemyapply"; then ok="post"; fi
  U="$(ab get url 2>/dev/null || echo '')"
  case "$U" in *Track*|*track*|*DocFollow*|*MyDoc*|*WorkDoc*) ok="nav"; break;; esac
  TOAST="$(ab eval "var t=document.querySelector('.layui-layer-content,.l-message'); t?t.innerText:''" 2>/dev/null | tr -d '"')"
  case "$TOAST" in *提交成功*) ok="toast"; break;; esac
  [ "$ok" = "post" ] && { sleep 2; }   # POST seen; give the redirect a moment
done

if [ -n "$ok" ]; then
  FINAL_URL="$(ab get url 2>/dev/null | head -c 120)"
  echo "SUBMITTED ($ok)"
  echo "URL: $FINAL_URL"
  # The portal has already accepted the application. Cleanup must never turn a
  # real success into a false failure: preserve the success result and warn if
  # the dedicated HNA automation browser cannot be closed.
  if close_hna_automation; then
    echo "AGENT_BROWSER_CLOSED"
  else
    echo "WARNING: submission succeeded, but HNA automation cleanup failed" >&2
  fi
  exit 0
fi

echo "UNCONFIRMED: no savemyapply POST / navigation / success toast observed" >&2
echo "Last toast: $(ab eval "var t=document.querySelector('.layui-layer-content,.l-message'); t?t.innerText:'none'" 2>/dev/null)" >&2
exit 2
