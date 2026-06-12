#!/usr/bin/env bash
# Fill the HNA leave-application form. Does everything EXCEPT the final submit
# (run submit.sh separately once the screenshot looks right).
#
# Inputs come in as environment variables so the skill can map parsed leave
# details onto them:
#
#   LEAVE_TYPE   休假类型, must match an <option> text (default 年休假)
#   BEGIN_DATE   起始时间, yyyy-MM-dd
#   END_DATE     结束时间, yyyy-MM-dd
#   PERIOD       休假时段: 全天 | 上半天 | 下半天 (default 全天)
#   REASON       休假原因 (default 个人原因。)
#   HANDOVER     工作交接情况 (default 工作自带。)
#   ADVICE       请示意见 full text (multi-line)
#   ATTACH_PATH  absolute path to the attachment PDF (optional)
#
# Why JS/jQuery instead of @eN refs for the field values: refs are reassigned on
# every snapshot and go stale the moment the page mutates. The form ships jQuery
# and a WdatePicker whose onpicked callback (WdPicker) computes 可休假 days and
# enables 休假时段 — driving those directly is far more stable than clicking the
# calendar widget. The ONE place a real ref click is required is the 固化流程
# button: it opens its picker via window.open(), which only fires from a trusted
# CDP gesture (a ref click), not from element.click()/CSS-selector clicks.
set -euo pipefail

PORT="${HNA_CDP_PORT:-9222}"
export LEAVE_TYPE="${LEAVE_TYPE:-年休假}"
export PERIOD="${PERIOD:-全天}"
export REASON="${REASON:-个人原因。}"
export HANDOVER="${HANDOVER:-工作自带。}"
export BEGIN_DATE="${BEGIN_DATE:-}"
export END_DATE="${END_DATE:-}"
export ADVICE="${ADVICE:-}"

ab() { agent-browser --cdp "${PORT}" "$@"; }
jset() { ab eval "window.__$1=$(python3 -c 'import json,os,sys;print(json.dumps(os.environ[sys.argv[1]]))' "$2")" >/dev/null 2>&1; }

# ---- Step 1: 固化流程 → pick 年休假流程 → confirm ------------------------------
# The 固化流程 button opens its flow picker in a new tab via window.open().
# Driving it with a CDP/ref click is unreliable (the jQuery handler often
# doesn't fire); calling the element's own .click() in page context fires the
# real handler every time, and --disable-popup-blocking lets the window.open
# succeed while keeping its window.opener link back to the form.
#
# Each `agent-browser --cdp` call re-resolves the active tab, so we manage tabs
# EXPLICITLY: capture the form tab id, switch to the popup by id, do the work,
# then switch back. Relying on auto-activation races against AJAX timing.
MAIN_ID="$(ab tab 2>/dev/null | grep LeaveApplicationLink | grep -oE '\bt[0-9]+\b' | head -1)"

POPUP_ID=""
for attempt in 1 2 3 4 5; do
  ab eval "var b=document.getElementById('btnFixedFlow'); b && b.click(); 'clicked'" >/dev/null 2>&1 || true
  sleep 2
  POPUP_ID="$(ab tab 2>/dev/null | grep oa3 | grep -oE '\bt[0-9]+\b' | head -1)"
  [ -n "$POPUP_ID" ] && break
done
if [ -z "$POPUP_ID" ]; then
  echo "ERROR: 固化流程 popup did not open (is Chrome launched with --disable-popup-blocking?)" >&2
  exit 1
fi

# Make the popup the active tab so all following commands target it.
ab tab "$POPUP_ID" >/dev/null 2>&1 || true
ab wait --load networkidle >/dev/null 2>&1 || true

# The flow list is populated by AJAX after load, so poll until the 年休假流程
# row actually exists before tagging it.
found=""
for _ in $(seq 1 20); do
  PRESENT="$(ab eval "Array.from(document.querySelectorAll('a')).some(function(a){return a.textContent.trim()==='年休假流程';}) ? 'yes':'no'" 2>/dev/null | tr -d '"')"
  [ "$PRESENT" = "yes" ] && { found=1; break; }
  sleep 1
done
if [ -z "$found" ]; then
  echo "ERROR: 年休假流程 row not found in 固化流程 popup" >&2
  exit 1
fi

# Tag the 选择 link on the 年休假流程 row, then click it with agent-browser so the
# resulting confirm() is catchable (a JS-triggered confirm would block eval).
ab eval --stdin <<'JS' >/dev/null 2>&1
(function(){
  var rows = document.querySelectorAll('tr');
  for (var i=0;i<rows.length;i++){
    var first = rows[i].querySelector('a');
    if (first && first.textContent.trim() === '年休假流程'){
      var links = rows[i].querySelectorAll('a');
      for (var j=0;j<links.length;j++){
        if (links[j].textContent.trim() === '选择'){ links[j].id='hnaPickFlow'; return; }
      }
    }
  }
})()
JS
ab click "#hnaPickFlow" >/dev/null 2>&1 || true
sleep 1
ab dialog accept >/dev/null 2>&1 || true            # 你确认所选择的流程吗？
sleep 2

# Confirm closes the popup; return to the form tab before touching fields.
ab tab "$MAIN_ID" >/dev/null 2>&1 || true
sleep 1

# ---- Step 2: attachment -------------------------------------------------------
# The visible 添加附件 button proxies to a hidden <input name=filedata>; set the
# file on that input directly — no OS file dialog to wrestle with.
if [ -n "${ATTACH_PATH:-}" ]; then
  if [ ! -f "$ATTACH_PATH" ]; then
    echo "ERROR: attachment not found: $ATTACH_PATH" >&2
    exit 2
  fi
  ab upload "input[name=filedata]" "$ATTACH_PATH" >/dev/null 2>&1
  sleep 2
fi

# ---- Step 3: push inputs into page context, then set type/dates/period --------
jset leaveType LEAVE_TYPE
jset begin     BEGIN_DATE
jset end       END_DATE
jset period    PERIOD
jset reason    REASON
jset handover  HANDOVER
jset advice    ADVICE

ab eval --stdin <<'JS' >/dev/null 2>&1
(function(){
  var $ = window.jQuery;
  // 类型
  $('.tbType').each(function(){
    var s=this; $(s).find('option').each(function(){
      if ($(this).text().trim()===window.__leaveType){ $(this).prop('selected',true); }
    });
    $(s).trigger('change');
  });
  // 起始/结束时间 → fire WdPicker to compute 可休假 days and validate order
  $('.tbBeginDate').val(window.__begin);
  $('.tbEndDate').val(window.__end);
  if (typeof WdPicker === 'function') WdPicker.call($('.tbEndDate')[0]);
  // 休假时段 (half-day only relevant for single-day requests)
  if (window.__period && window.__period !== '全天'){
    var sel = $('.vacationPeriod, .tbVacPeriod').first();
    if (sel.length){
      sel.prop('disabled', false);
      sel.find('option').each(function(){
        if ($(this).text().trim()===window.__period){ $(this).prop('selected',true); }
      });
      sel.trigger('change');
    }
  }
})()
JS
sleep 1

# ---- Step 4: reason / handover / advice --------------------------------------
ab eval --stdin <<'JS' >/dev/null 2>&1
(function(){
  var $ = window.jQuery;
  $('textarea.DESCR200').val(window.__reason).trigger('change');     // 休假原因
  $('textarea.DESCR254').val(window.__handover).trigger('change');   // 工作交接情况
  $('textarea[name="ctl00$MainContentPortal$tbRPTCMMT"]').val(window.__advice).trigger('change'); // 请示意见
})()
JS
sleep 1

echo "FILLED"
