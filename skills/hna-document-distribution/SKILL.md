---
name: hna-document-distribution
description: >-
  公文分发 on the HNA OA portal (oa3.hnair.net 公文查询 / QueryToView.aspx).
  Use whenever the user wants to 分发公文, 公文分发, 把公文分给某人, 发给收件人,
  or names a 办文编号 plus a recipient. The workflow uses Ego Browser: it finds
  the finished document, types the recipient, and selects the exact person.
  It never clicks 公文分发 during preview. That click happens only after the
  user explicitly asks to submit the already reviewed form.
---

# HNA 公文分发

Use Ego Browser, not `agent-browser`, Chrome CDP, saved browser-state files, or
custom browser processes. Ego Lite isolates this workflow from the user's usual
browser. A missing or expired SSO session is normal: hand the OA page to the
user to log in, then resume the **same** task space.

This skill distributes one already approved document to one recipient. It does
not 呈报 a new document, and it does not use 批量分发.

## Inputs and safety rules

| Field | Rule |
| --- | --- |
| Document | Require `docId` (办文编号) or `title`. Same titles repeat; if more than one row matches, stop and ask for 办文编号 or the exact `submitTime`. |
| Category | Default `我呈报的公文`. Use another category only when the user names it. |
| Year | Default the current calendar year. |
| Recipient | `recipientName` is the text typed into 收件人. Never pick the first autocomplete row. |
| Disambiguation | If the dropdown has more than one person, require `account` (the bracket login, such as `zhang-xia`) or `department`. `[zhang-xia]` must not match `zhangxia2`. |
| Submit | Never click `公文分发`, `批量分发`, or the lower `分发` button unless the user explicitly asks to submit the reviewed form. |

Do not invent a recipient id. Only the autocomplete result callback may fill
`txbRecID` and the related hidden fields. If those fields stay empty after the
click, stop.

A name already present under 已分发人员 is not an error and is not permission
to submit. Report it in the preview.

Classified documents (`strSec != 0201`) raise a confirm inside `check()`.
Accept that confirm only inside the submit helper, after an explicit submit
request. A preview must not accept it.

## Stage a recipient without distributing

1. Confirm the document key and the recipient identity. If the name is
   ambiguous, get `account` or `department` before opening the form.
2. Start an Ego task space and execute the stage helper. It reports
   `login_required`, `ambiguous`, or `filled_preview`.

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/hna-document-distribution/scripts/stage.mjs";

await stage({
  docId: "31908462",
  recipientName: "张霞",
  account: "zhang-xia",
  department: "运维安全中心",
});
EOF
```

3. If the helper returns `login_required`, it has called `task.handOff()`.
   Tell the user to log in in the Ego Lite tab. Once they confirm, continue
   from the same task space with the same arguments plus `taskSpaceId`.

The helper opens `http://oa3.hnair.net/oawebapp/index.aspx`, clicks 公文查询,
runs the query, and opens `QueryToView.aspx` directly. Do not rely on
`OpenHQNewShow`: it calls `window.open`, and that popup is not a reliable
tracked page. Recipient search must dispatch `keydown` after setting the input.
`fill` and `keyboard.type` leave the old jQuery autocomplete closed. The helper
checks `txbRecID`, `txbAllRec`, and the account token, saves a local screenshot,
reports `submitted: false`, and hands the form to the user.

## Submit only after explicit approval

Only after the user explicitly asks to distribute the already reviewed form,
reclaim the displayed task space and call:

```bash
ego-browser nodejs <<'EOF'
import { submit } from "/Users/jarod/Documents/agent-skills/skills/hna-document-distribution/scripts/submit.mjs";
await submit({ taskSpaceId: <TASK_SPACE_ID> });
EOF
```

The submit helper refuses an empty recipient, clicks `#UcAllotAdv1_btDocAllot`
exactly once, and accepts the classification confirm only if that dialog
appears. It does not click again. Success requires the reloaded 分发信息 text
to change. An unchanged page is `needs_review`, not success. The page stays
open for inspection.
