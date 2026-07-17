#!/usr/bin/env bash
# Fill the HNA leave-application form. Does everything EXCEPT the final submit
# (run submit.sh separately once the screenshot looks right).
#
# Inputs come in as environment variables so the skill can map parsed leave
# details onto them:
#
#   LEAVE_TYPE      休假类型, must match an <option> text (default 年休假)
#   FLOW_NAME       固化流程名称. 补休默认倒休流程；年休假默认年休假流程。
#   BEGIN_DATE      起始时间, yyyy-MM-dd
#   END_DATE        结束时间, yyyy-MM-dd
#   PERIOD          休假时段: 全天 | 上半天 | 下半天 (default 全天)
#   REASON          休假原因 (default 个人原因。)
#   HANDOVER        工作交接情况 (default 工作自带。)
#   ADVICE_BODY     请示意见正文；不要包含称呼、缩进或附件行。
#   ADVICE_GREETING 请示意见称呼 (default 各位领导，)
#   ATTACH_PATH     审批邮件 PDF 的绝对路径（标准模板必填）
#   ATTACH_LABEL    附件行名称；默认使用 ATTACH_PATH 的无扩展名文件名。
#
# Legacy ADVICE is deliberately rejected. It previously allowed an unformatted
# full text value to bypass the required 请示意见 template.
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
export FLOW_NAME="${FLOW_NAME:-}"
export ADVICE_BODY="${ADVICE_BODY:-}"
export ADVICE_GREETING="${ADVICE_GREETING:-各位领导，}"
export ATTACH_PATH="${ATTACH_PATH:-}"
export ATTACH_LABEL="${ATTACH_LABEL:-}"

if [ -n "${ADVICE:-}" ]; then
  echo "ERROR: ADVICE is no longer accepted; pass the body through ADVICE_BODY so the required 请示意见 template is applied" >&2
  exit 3
fi

case "$LEAVE_TYPE" in
  补休) FLOW_NAME="${FLOW_NAME:-倒休流程}" ;;
  年休假) FLOW_NAME="${FLOW_NAME:-年休假流程}" ;;
  *)
    if [ -z "$FLOW_NAME" ]; then
      echo "ERROR: FLOW_NAME is required for leave type: $LEAVE_TYPE" >&2
      exit 3
    fi
    ;;
esac
export FLOW_NAME

if [ -z "$ADVICE_BODY" ]; then
  echo "ERROR: ADVICE_BODY is required; provide only the factual body, without greeting or attachment line" >&2
  exit 3
fi

if [ -z "$ATTACH_PATH" ]; then
  echo "ERROR: ATTACH_PATH is required for the standard 请示意见 template and attachment verification" >&2
  exit 3
fi

if [ -z "$ATTACH_LABEL" ]; then
  ATTACH_LABEL="$(basename "$ATTACH_PATH")"
  ATTACH_LABEL="${ATTACH_LABEL%.*}"
fi
export ATTACH_LABEL

format_advice() {
  printf '%s\n' "$ADVICE_GREETING"
  printf '%s\n' "$ADVICE_BODY" | sed \
    -e 's/\r$//' \
    -e '/^[[:space:]]*$/d' \
    -e 's/^[[:space:]]*//' \
    -e 's/[[:space:]]*$//' \
    -e 's/^/    /'
  printf '附件：%s' "$ATTACH_LABEL"
}

export ADVICE="$(format_advice)"

# Offline template check for the agent before it touches the HR portal.
if [ "${HNA_FORMAT_ADVICE_ONLY:-0}" = "1" ]; then
  printf '%s\n' "$ADVICE"
  exit 0
fi

ab() { agent-browser --cdp "${PORT}" "$@"; }
jset() { ab eval "window.__$1=$(python3 -c 'import json,os,sys;print(json.dumps(os.environ[sys.argv[1]]))' "$2")" >/dev/null 2>&1; }

# ---- Step 1: 固化流程 → pick the selected flow → confirm ----------------------
# The 固化流程 button opens its flow picker in a new tab via window.open().
# Driving it with a CDP/ref click is unreliable (the jQuery handler often
# doesn't fire); calling the element's own .click() in page context fires the
# real handler every time, and --disable-popup-blocking lets the window.open
# succeed while keeping its window.opener link back to the form.
#
# Each `agent-browser --cdp` call re-resolves the active tab, so we manage tabs
# EXPLICITLY: capture the form tab id, switch to the popup by id, do the work,
# then switch back. Relying on auto-activation races against AJAX timing.
MAIN_ID="$(ab tab 2>/dev/null | grep LeaveApplicationLink | grep -oE '\bt[0-9]+\b' | head -1 || true)"
if [ -z "$MAIN_ID" ]; then
  echo "ERROR: leave-application form tab not found" >&2
  exit 1
fi

# A user may already have unrelated oa3.hnair.net pages open (for example,
# 公文跟踪). Record any existing real flow-picker tabs, then accept only a new
# MyFlow.aspx tab opened by the 固化流程 button below.
PREEXISTING_FLOW_IDS="$(ab tab 2>/dev/null | awk '/oa3\.hnair\.net\/OAWebApp\/OA\/Workflow\/Process\/MyFlow\.aspx/ { if (match($0, /t[0-9]+/)) print substr($0, RSTART, RLENGTH) }')"

POPUP_ID=""
for attempt in 1 2 3 4 5; do
  # Each agent-browser call targets whichever tab is active. Explicitly return
  # to the leave form before invoking its page-local 固化流程 handler.
  if ! ab tab "$MAIN_ID" >/dev/null 2>&1; then
    echo "ERROR: could not activate the leave-application form tab" >&2
    exit 1
  fi
  ab eval "var b=document.getElementById('btnFixedFlow'); b && b.click(); 'clicked'" >/dev/null 2>&1 || true
  sleep 2
  CANDIDATE_FLOW_IDS="$(ab tab 2>/dev/null | awk '/oa3\.hnair\.net\/OAWebApp\/OA\/Workflow\/Process\/MyFlow\.aspx/ { if (match($0, /t[0-9]+/)) print substr($0, RSTART, RLENGTH) }')"
  for candidate in $CANDIDATE_FLOW_IDS; do
    case " $PREEXISTING_FLOW_IDS " in
      *" $candidate "*) ;;
      *) POPUP_ID="$candidate"; break ;;
    esac
  done
  [ -n "$POPUP_ID" ] && break
done
if [ -z "$POPUP_ID" ]; then
  echo "ERROR: 固化流程 popup did not open (is Chrome launched with --disable-popup-blocking?)" >&2
  exit 1
fi

# Make the popup the active tab so all following commands target it.
if ! ab tab "$POPUP_ID" >/dev/null 2>&1; then
  echo "ERROR: could not activate the 固化流程 popup" >&2
  exit 1
fi
ab wait --load networkidle >/dev/null 2>&1 || true
jset flowName FLOW_NAME

# The popup lives on oa3.hnair.net behind its own SSO. If the SSO master
# session idle-expired since launch.sh ran, the popup bounces to the login
# page — fail loudly so the caller re-runs launch.sh (which handles login).
POPUP_URL="$(ab get url 2>/dev/null || echo '')"
case "$POPUP_URL" in
  *login.hnagroup.com*|*ssocallback*)
    echo "ERROR: SSO_EXPIRED — 固化流程 popup bounced to the SSO login page; re-run launch.sh and log in" >&2
    exit 12
    ;;
esac

# The flow list is populated by AJAX after load, so poll until the selected
# flow row actually exists before tagging it.
found=""
for _ in $(seq 1 20); do
  PRESENT="$(ab eval "Array.from(document.querySelectorAll('a')).some(function(a){return a.textContent.trim()===window.__flowName;}) ? 'yes':'no'" 2>/dev/null | tr -d '"')"
  [ "$PRESENT" = "yes" ] && { found=1; break; }
  sleep 1
done
if [ -z "$found" ]; then
  echo "ERROR: $FLOW_NAME row not found in 固化流程 popup" >&2
  exit 1
fi

# Tag the 选择 link on the selected flow row, then click it with agent-browser so the
# resulting confirm() is catchable (a JS-triggered confirm would block eval).
ab eval --stdin <<'JS' >/dev/null 2>&1
(function(){
  var rows = document.querySelectorAll('tr');
  for (var i=0;i<rows.length;i++){
    var first = rows[i].querySelector('a');
    if (first && first.textContent.trim() === window.__flowName){
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
if ! ab tab "$MAIN_ID" >/dev/null 2>&1; then
  echo "ERROR: could not return to the leave-application form tab" >&2
  exit 1
fi
sleep 1

# ---- Step 2: attachment -------------------------------------------------------
# The visible 添加附件 button proxies to a hidden <input name=filedata>; set the
# file on that input directly — no OS file dialog to wrestle with. Validate the
# visible attachment list rather than the unreliable input value.
if [ ! -f "$ATTACH_PATH" ]; then
  echo "ERROR: attachment not found: $ATTACH_PATH" >&2
  exit 2
fi
ATTACH_NAME="$(basename "$ATTACH_PATH")"
export ATTACH_NAME
ab upload "input[name=filedata]" "$ATTACH_PATH" >/dev/null 2>&1
jset attachmentName ATTACH_NAME
ATTACHMENT_LISTED=""
for _ in $(seq 1 10); do
  ATTACHMENT_LISTED="$(ab eval "Array.from(document.querySelectorAll('td')).some(function(cell){return cell.textContent.trim()===window.__attachmentName;}) ? 'yes':'no'" 2>/dev/null | tr -d '"')"
  [ "$ATTACHMENT_LISTED" = "yes" ] && break
  sleep 1
done
if [ "$ATTACHMENT_LISTED" != "yes" ]; then
  echo "ERROR: attachment is not visible in the attachment list: $ATTACH_NAME" >&2
  exit 2
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

ADVICE_WRITTEN="$(ab eval "var a=document.querySelector('textarea[name*=\"tbRPTCMMT\"]'); a && a.value===window.__advice ? 'yes':'no'" 2>/dev/null | tr -d '"')"
if [ "$ADVICE_WRITTEN" != "yes" ]; then
  echo "ERROR: 请示意见 was not written exactly as the generated template" >&2
  exit 4
fi

echo "FILLED"
echo "FLOW_NAME: $FLOW_NAME"
echo "ADVICE_FORMAT: standard"
