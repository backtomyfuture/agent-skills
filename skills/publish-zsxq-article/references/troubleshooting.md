# Zsxq troubleshooting

## Ego Lite and TaskSpace

Run all browser work through `ego-browser nodejs` and the helpers in
`scripts/`. A TaskSpace is created once for a run. If the stage helper reports
`login_required`, it has already called `task.handOff()`. Ask the user to log
in in the handed-off Zsxq tab, then invoke `stage({ taskSpaceId, ... })` with
the same numeric ID.

Do not create another TaskSpace to recover from a login or editor problem.
Inspect the existing page with `page.snapshot()` or `page.screenshot()`, then
continue in that TaskSpace. Do not close or finish a TaskSpace while waiting
for the user.

## Editor mode

The target editor is Milkdown:

- `.ProseMirror` means Markdown mode and must exist before body insertion.
- `.ql-editor` means rich-text mode. The stage helper clicks `.toggle-mode`,
  confirms the mode switch, and waits for `.ProseMirror`.

If Markdown appears as literal `#` or `*`, the body code was not evaluated in
the page or the editor was still in Quill mode. Re-run staging against a clean
review page, confirm `.ProseMirror`, and let `stage.mjs` evaluate the generated
`prepare_content.py` output. Never replace this with `fill()` or keyboard
typing.

After switching modes, Zsxq may show `恢复上次编辑的内容`. The safe action is
the exact `忽略` button. Do not click a generic `.confirm` control after the
switch because it can restore old content.

## Body and image insertion

`prepare_content.py` emits a self-contained JavaScript IIFE for a synthetic
text `ClipboardEvent`. `prepare_image.py` emits a separate IIFE containing a
binary `ClipboardEvent`. The stage helper evaluates both with
`page.evaluate()`; the code runs in the browser page and cannot use Node.js
modules.

For each image, marker deletion, the 500 ms synchronization wait, and image
evaluation must remain three separate actions. Combining them can leave the
ProseMirror selection at the old position and place the image incorrectly.

The stage verification excludes ProseMirror separator images and requires:

- at least one body block;
- zero remaining `[[IMG_N]]` markers;
- the visible image count equal to the number of staged image entries.

If an image is missing, check the JSON from `prepare_content.py` and ensure its
`resolved_path` exists. Regenerate its image code with
`prepare_image.py`; do not guess a path or alter the original Markdown.

## Scheduling

Staging never schedules or publishes. Only call `submit.mjs` after explicit
authorization. It must find the same article tab, enable the
`.scheduled-topic-timer` switch, set the flatpickr date to tomorrow, and choose
hour `10` and minute `00` (the UI may display the minute as `0`).

Before the click, the helper reads `.operation-btns .post.btn` and requires the
exact text `定时发布`. If it reads `发布`, stop: clicking would publish
immediately. If the click has no observable success within the wait window,
the helper reports `click_sent_unverified` and intentionally does not retry.

## Notion image failures

Notion image URLs are signed and can expire. If `notion_ingest.py` reports
`failed_count > 0`, stop before browser work and ask whether to re-fetch the
page or proceed with the named image(s) omitted. Never stage a silently broken
article.

## Local artifacts

Screenshots from staging are written to `/tmp/zsxq-article/`. Generated body
and image code belongs in `/tmp` or another scratch directory. The user's
Markdown, Notion page, and source images are never modified.
