---
name: publish-zsxq-article
description: >-
  Stage and, after explicit authorization, schedule an article in Zsxq
  (知识星球 / wx.zsxq.com) for tomorrow at 10:00 from a Notion page or local
  Markdown file. Use whenever the user asks to publish an article to Zsxq,
  知识星球, 星球文章, or wx.zsxq.com. The workflow always uses Ego Lite and
  never performs an instant publish.
---

# Publish a Zsxq Article

This skill prepares an article in the Zsxq Milkdown/ProseMirror editor, hands
the page to the user for review, and only schedules it after the user explicitly
authorizes scheduling. Scheduling for tomorrow at 10:00 is the only submit path;
never click a button whose exact text is `发布`.

The workflow uses one Ego Lite TaskSpace for the entire run. If login is
needed, the stage helper reports `login_required`, hands off that TaskSpace,
and the next stage call must use the returned `taskSpaceId`. Do not create a
second TaskSpace for login or recovery.

## Configuration

This skill is tuned for the `AI 一天` group:

- Group ID: `88882188185282`
- Article URL: `https://wx.zsxq.com/article?groupId=88882188185282`
- Login URL: `https://wx.zsxq.com/login`

If the user requests another group, confirm its group ID before proceeding.

## Safety boundary

- `scripts/stage.mjs` only stages content and hands off the filled page. It
  always reports `submitted: false`.
- `scripts/submit.mjs` may be called only after the user explicitly authorizes
  scheduling the reviewed page.
- The submit helper enables scheduling, sets tomorrow at 10:00, verifies the
  exact button text `定时发布`, and only then clicks. It refuses every other
  button text, especially `发布`.
- A click with no observable success is reported as
  `click_sent_unverified`; it is never retried.
- Do not click `保存`, navigate away to create a separate draft, or submit
  while staging. The scheduled article remains reviewable in `我的文章`.

## Prerequisites

- Ego Lite (`ego-browser` command)
- Python 3 for the preparation helpers
- Optional: Pillow for resizing very large images

## Prepare source content

For a Notion URL, fetch it with the authenticated Notion tool before browser
work. Write the returned Markdown to `/tmp/zsxq-notion/raw.md`, then localize
its images:

```bash
mkdir -p /tmp/zsxq-notion
python3 /Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/notion_ingest.py \
  --input /tmp/zsxq-notion/raw.md \
  --output-dir /tmp/zsxq-notion
```

Inspect the JSON summary. If `failed_count` is nonzero, stop and ask whether
to re-fetch the Notion page for fresh signed URLs or proceed with the missing
images skipped. Never silently stage an article with broken image references.

For a local Markdown file, use it directly. Then generate the body code:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/prepare_content.py \
  '/absolute/path/article.md' \
  --output /tmp/zsxq_paste_content.js
```

The summary contains `title`, `js_file`, and ordered `images`. The helper
extracts the first H1 (or filename), replaces images with `[[IMG_N]]` markers,
and emits code for a synthetic `ClipboardEvent`. Do not edit the source file.

For each image with a non-null `resolved_path`, generate a distinct image code
file and pass its path with the matching marker to the stage helper:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/prepare_image.py \
  '/absolute/path/image.png' \
  --output /tmp/zsxq_paste_image_1.js
```

If a `resolved_path` is null, do not call stage with its marker still in the
body. Ask whether to re-fetch the Notion page or proceed without that image;
for the latter, remove that failed image reference from the scratch
`/tmp/zsxq-notion/article.md`, rerun `prepare_content.py`, and regenerate the
remaining image code files. Never modify the user's original source. Image code
contains the binary paste operation only.

## Stage in Ego Lite

Run the helper inside `ego-browser nodejs`; it creates or reclaims one
TaskSpace, opens the article URL, detects login, switches to Markdown mode,
dismisses `忽略`, fills the title, and evaluates the generated body code in the
page:

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/stage.mjs";

await stage({
  title: "Title from prepare_content.py",
  bodyJsPath: "/tmp/zsxq_paste_content.js",
  images: [
    {
      marker: "[[IMG_1]]",
      pasteJsPath: "/tmp/zsxq_paste_image_1.js",
    },
  ],
});
EOF
```

The image loop is intentionally three separate page actions for every image:

1. `page.evaluate()` deletes the marker through ProseMirror's transaction.
2. `page.waitForTimeout(500)` lets ProseMirror synchronize its selection.
3. `page.evaluate()` evaluates the generated binary image code.

The helper verifies the ProseMirror body, confirms there are no remaining
markers, checks the visible image count, writes a screenshot under
`/tmp/zsxq-article/`, prints `status: "staged"` and `submitted: false`, then
hands off the page.

If it prints `login_required`, ask the user to log in in the handed-off Ego
Lite tab. After the user confirms login, resume the **same** TaskSpace:

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/stage.mjs";

await stage({
  taskSpaceId: 123,
  title: "Title from prepare_content.py",
  bodyJsPath: "/tmp/zsxq_paste_content.js",
  images: [],
});
EOF
```

Use the actual `taskSpaceId` from the prior JSON output. Do not repeat the
initial navigation in a new TaskSpace.

## Schedule only after explicit authorization

After the user reviews the handed-off page and explicitly asks to schedule it,
reclaim the same TaskSpace:

```bash
ego-browser nodejs <<'EOF'
import { submit } from "/Users/jarod/Documents/agent-skills/skills/publish-zsxq-article/scripts/submit.mjs";

await submit({ taskSpaceId: 123 });
EOF
```

The helper uses the existing flatpickr date input and Zsxq time-picker lists,
sets tomorrow at 10:00, verifies the exact text `定时发布`, and clicks once.
On success it reports the scheduled date/time and keeps the result page open.
On an unverified click it reports an error and does not retry.

## Troubleshooting

See [`references/troubleshooting.md`](references/troubleshooting.md) for
Ego Lite login handoff, editor mode, image synchronization, and scheduling
recovery guidance. See [`references/editor-internals.md`](references/editor-internals.md)
for the Milkdown/ProseMirror insertion model.
