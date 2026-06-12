#!/usr/bin/env bash
# Submit the leave application and verify it actually reached the server.
# This is the irreversible step — only run it after the filled form has been
# visually confirmed.
#
# The 提交 <button> carries onclick="checkFormMain()". A CDP/ref click does NOT
# reliably fire that handler (same gotcha as the 固化流程 button), so we invoke
# checkFormMain() directly in page context — it is exactly what the button does:
# validates via checkForm(), then POSTs to /EHR/Handler/LeaveApplication.ashx
# (action=savemyapply) and, on success, shows "提交成功…" and redirects to the
# 公文跟踪 page.
#
# We confirm success by watching for that navigation / success toast AND by
# checking the network log for the savemyapply POST — so we never report a
# submit that didn't happen, and never fire twice.
set -euo pipefail

PORT="${HNA_CDP_PORT:-9222}"
ab() { agent-browser --cdp "${PORT}" "$@"; }

# Clear any stale layer toast left over from a previous attempt.
ab eval "if(typeof layer!=='undefined'&&layer.closeAll){layer.closeAll();}'cleared'" >/dev/null 2>&1 || true

# Guard against double-submit: if a savemyapply POST already went out, stop.
if ab network requests 2>/dev/null | grep -q "savemyapply"; then
  echo "ALREADY_SUBMITTED: a savemyapply request is already in the network log" >&2
  exit 3
fi

# Validate first; checkForm() returns false (and toasts) if something's missing.
VALID="$(ab eval "typeof checkForm==='function' ? String(checkForm()) : 'nofunc'" 2>/dev/null | tr -d '"')"
if [ "$VALID" != "true" ]; then
  echo "ERROR: form validation (checkForm) did not pass: $VALID" >&2
  exit 1
fi

# Fire the real submit.
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
  echo "SUBMITTED ($ok)"
  echo "URL: $(ab get url 2>/dev/null | head -c 120)"
  exit 0
fi

echo "UNCONFIRMED: no savemyapply POST / navigation / success toast observed" >&2
echo "Last toast: $(ab eval "var t=document.querySelector('.layui-layer-content,.l-message'); t?t.innerText:'none'" 2>/dev/null)" >&2
exit 2
