---
name: hna-leave-application
description: >-
  Submit or preview a leave/休假 application (公文呈报) on the HNA HR portal
  (hr.hna.net 休假申请 / LeaveApplicationLink.aspx). Use this skill whenever the
  user wants to 请假, 提交休假申请, 走年休假/补休/事假/病假流程, 呈报休假公文, "帮我申请休假",
  "提交休假呈报", "填报休假公文", "报休假公文", or gives an approval-email PDF. The
  newest/topmost approved request supplies the leave details and the PDF is
  attached to the form. The workflow uses Ego Browser: it hands off the
  isolated HNA tab for manual SSO login only, then resumes the same task space
  to select the flow, fill the form, attach the PDF, and verify it. Submission
  occurs only after the user explicitly requests it.
---

# HNA 休假申请呈报

Use Ego Browser, not `agent-browser`, Chrome CDP, saved browser-state files, or
custom browser processes. Ego Lite isolates this workflow from the user's usual
browser. A missing or expired SSO session is normal: hand the HNA page to the
user to log in, then resume the **same** task space.

## Inputs and safety rules

The standard input is the manager-approval email exported as a PDF. It supplies
the values below and is also the required attachment:

| Field | Rule |
| --- | --- |
| Dates and duration | Read only the newest request directly below the topmost approval. Cross-check its email subject. |
| Leave type | Map `倒休` to `补休`; use the portal's exact option text for other leave types. |
| Flow | Default `倒休流程` for 补休 and `年休假流程` for 年休假. Require an explicit flow for other leave types. |
| Period | `全天` by default. A multi-day request with specified daily hours stays `全天`; preserve its hours in 请示意见. |
| Reason / handover | `个人原因。` and `工作自带。` unless the user gives replacements. |
| 请示意见 | Use only the factual request text. The staging script adds `各位领导，`, four-space indentation, and the attachment line. |

Normalize extracted PDF text with NFKC before parsing. Restore Chinese
punctuation in the final 请示意见. Never use a historical request without calling
out that its leave dates have passed and getting the user's explicit test-only
approval.

Never submit during a preview or filling request. Do not use a system's
"撤回" capability as a substitute for the user's submission authorization.

## Stage a form without submitting

1. Read and verify the PDF. Confirm the topmost reply approves the newest
   request. Derive `leaveType`, `flowName`, dates, and `adviceBody`.
2. Start an Ego task space and execute the stage helper. It opens the leave
   form and reports either `login_required` or `filled_preview`.

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/hna-leave-application/scripts/stage.mjs";

await stage({
  attachmentPath: "/absolute/path/中心经理审批邮件.pdf",
  leaveType: "补休",
  flowName: "倒休流程",
  beginDate: "2026-09-01",
  endDate: "2026-09-03",
  period: "全天",
  adviceBody: [
    "因个人原因，申请9月1日、2日、3日每天下午4:30至5:30休假1小时，使用8月倒休3小时。",
    "使用前8月倒休共计8小时，本次使用3小时，使用后剩余5小时。",
    "原有开发工作已妥善安排，均按照正常计划开展，休假期间，工作自带。",
    "妥否，请领导批示。",
  ].join("\n"),
});
EOF
```

3. If the helper returns `login_required`, it has called `task.handOff()`.
   Tell the user to log in in the Ego Lite tab. Once they confirm, continue
   from the same task space:

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/hna-leave-application/scripts/stage.mjs";

await stage({
  taskSpaceId: <TASK_SPACE_ID>,
  attachmentPath: "/absolute/path/中心经理审批邮件.pdf",
  leaveType: "补休",
  flowName: "倒休流程",
  beginDate: "2026-09-01",
  endDate: "2026-09-03",
  period: "全天",
  adviceBody: "<verified factual request text>",
});
EOF
```

The helper opens the 固化流程 picker, selects the requested flow, accepts its
confirmation dialog, uploads the PDF to the hidden file field, sets the
dates/type/fields through the portal's jQuery and WdatePicker integration, and
checks the visible attachment plus exact 请示意见 text. It saves a local screenshot
for agent review, reports `submitted: false`, and hands the filled form to the
user. Do not click 提交 in this flow.

## Submit only after explicit approval

Only after a user explicitly asks to submit the already reviewed form, reclaim
the displayed task space and call:

```bash
ego-browser nodejs <<'EOF'
import { submit } from "/Users/jarod/Documents/agent-skills/skills/hna-leave-application/scripts/submit.mjs";
await submit({ taskSpaceId: <TASK_SPACE_ID> });
EOF
```

The submit helper blocks repeated submission in the same document, invokes the
portal's `checkFormMain()` exactly once, then requires navigation to the
expected tracking/result page after it finishes loading. It captures that
returned page locally and reports its title, URL, and visible text summary
before reporting success. The returned page remains open in Ego Lite for the
user to inspect.
