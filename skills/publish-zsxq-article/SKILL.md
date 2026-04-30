---
name: publish-zsxq-article
description: Publish an article to Zsxq (知识星球 / wx.zsxq.com) as a scheduled post for the next day, from either a Notion page URL or a local Markdown file. ALWAYS use this skill whenever the user mentions 知识星球, 星球, zsxq, wx.zsxq, 星球文章, 发到星球, 发布到知识星球, publish to Zsxq, post to Zsxq, or asks to turn a Notion page / Markdown file / article note into a Zsxq post — even if they don't explicitly say "schedule" or "定时". Handles Notion-page ingest (fetches Markdown via MCP, downloads inline images, preserves image positions), Markdown parsing, image insertion via synthetic ClipboardEvent, and scheduled publish. Never publishes instantly; always schedules for a later time so the user can review in "我的文章" before the post goes live.
---

# Publish Zsxq Article

Publish an article to the Zsxq (知识星球) article editor in Markdown mode and schedule it for the next day. The source is either a Notion page (via URL) or a local Markdown file. The skill never publishes instantly — it always schedules the post for a later time, which is functionally a draft until that time arrives and gives the user a window to review in "我的文章" before it goes live.

The editor is a Milkdown/ProseMirror WYSIWYG that parses Markdown only when it arrives via a paste event. So the whole skill is structured around constructing the right paste events and dispatching them at the right moments. Helper Python scripts build those events for us so we don't have to wrestle with JS escaping in the shell.

## Prerequisites

- [agent-browser](https://github.com/agent-browser/agent-browser) CLI (`npm i -g agent-browser && agent-browser install`)
- Python 3 for the helper scripts in `scripts/`
- Optional: `Pillow` (only needed if you plan to insert large images that need compression)

## Group configuration

The skill always publishes to the "AI 一天" group:

- **Group ID:** `88882188185282`
- **Editor URL:** `https://wx.zsxq.com/article?groupId=88882188185282`
- **Login URL:** `https://wx.zsxq.com/login`

If the user mentions a different group, stop and confirm the group ID with them before proceeding — the skill is tuned for this one group.

## Helper scripts

All scripts live in this skill's `scripts/` directory. Use absolute paths when invoking them:

- `/Users/jarod/.agents/skills/publish-zsxq-article/scripts/notion_ingest.py` — takes raw Markdown from the Notion MCP `notion-fetch` tool, downloads all inline images locally, and rewrites references to local paths while preserving positions.
- `/Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_content.py` — preprocesses Markdown and writes a paste-ready JS file.
- `/Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_image.py` — base64-encodes an image and writes a paste-ready JS file.

## Workflow

The skill runs four pipelines in order. The first two are always required; the image pipeline only runs when the article has images; the publish pipeline always runs last.

1. **Pre-flight** — clean up any leftover browser session and confirm we're logged into Zsxq.
2. **Content pipeline** — if the source is a Notion URL, fetch it and localize its images first. Then prepare the Markdown, open the editor in Markdown mode, fill the title, and paste the body.
3. **Image pipeline** — for each image the content pipeline extracted, delete its placeholder marker and paste the real image into the cursor position.
4. **Publish pipeline** — schedule the post for tomorrow 10:00. No separate "save draft" step: a scheduled post is functionally a draft until its publish time, so saving first would be redundant and slows the run.

## Pre-flight

### Clean up leftover sessions

agent-browser maintains a background daemon per session. If a previous headless daemon is still running, it silently refuses to upgrade to headed mode, which makes later login-debugging painful. Close everything once at the start:

```bash
agent-browser close --all
```

Do this only once per skill invocation. Don't loop.

### Open the editor and check login in one shot

Prefer opening the editor URL directly rather than the login page. If the session is valid you're already where you need to be; if it's expired Zsxq redirects to `/login`, which is an equally clear signal.

First check whether a persistent Chrome profile exists — it's more reliable than state JSON because it carries the real Chrome cookie jar:

```bash
ls ~/.agent-browser/profiles/zsxq/ 2>/dev/null && echo "PROFILE_FOUND"
```

Open with the profile if available, without otherwise:

```bash
# With profile
agent-browser --headed true --session-name zsxq --profile ~/.agent-browser/profiles/zsxq/ open "https://wx.zsxq.com/article?groupId=88882188185282"

# Without profile
agent-browser --headed true --session-name zsxq open "https://wx.zsxq.com/article?groupId=88882188185282"
```

Then check login state in a single eval. The title input only exists on the editor page, and a redirect to `/login` shows up in `location.href`:

```bash
agent-browser wait 3000
agent-browser --session-name zsxq eval '(() => { const hasTitle = !!document.querySelector("input[placeholder=请在这里输入标题]"); const url = location.href; return { loggedIn: hasTitle && !url.includes("/login"), url }; })()'
```

If `loggedIn` is true, continue to the content pipeline. If false, walk the user through the manual login flow in [`references/troubleshooting.md`](references/troubleshooting.md#login-problems), then resume here. Check only once — looping doesn't help when the problem is an expired session.

## Content pipeline

### If the source is a Notion URL, ingest it first

When the user gives you a Notion page link (e.g. `https://www.notion.so/workspace/Article-Title-abc123`), you need to convert it into a local Markdown file plus local image files before `prepare_content.py` can do its job. Zsxq's Milkdown editor only accepts image uploads via binary paste, so every image referenced in the post must exist on disk.

Two calls do this:

1. Fetch the page via the Notion MCP tool:

   ```
   notion___notion-fetch(id="<the Notion URL or page UUID>")
   ```

   This returns the page body as enhanced Markdown. Extract the article body from the response — strip any leading property blocks, `<page-discussions>` tags, or similar wrappers the MCP adds around the actual content. What you want is the Markdown the author wrote, with `![alt](url)` image references pointing at Notion's signed URLs.

2. Pipe that Markdown into `notion_ingest.py`, giving it an output directory:

   ```bash
   mkdir -p /tmp/zsxq-notion
   # Write the extracted Markdown to /tmp/zsxq-notion/raw.md first, then:
   python3 /Users/jarod/.agents/skills/publish-zsxq-article/scripts/notion_ingest.py \
     --input /tmp/zsxq-notion/raw.md \
     --output-dir /tmp/zsxq-notion
   ```

   The script downloads every remote image into the output directory and rewrites the Markdown so each `![alt](url)` becomes `![alt](img_N.ext)` at the same position. Image ordering and position within the text are preserved — this matters because they're what the image pipeline later uses to anchor each image to its intended spot in the post.

   The JSON summary tells you which images downloaded successfully and which failed (expired signed URLs, network errors, etc.). If `failed_count > 0`, stop and ask the user whether to re-fetch the Notion page (signed URLs are time-limited) or to skip the missing images.

From here on, treat `/tmp/zsxq-notion/article.md` exactly like any other local Markdown file and continue with `prepare_content.py` below.

### Prepare the Markdown

`prepare_content.py` does several things in one pass so the rest of the skill can be dumb: strips Notion export metadata, extracts the title from the first H1 (or falls back to the filename), replaces image references with `[[IMG_N]]` placeholders and records their resolved paths, and emits a self-contained JS file that dispatches the right synthetic paste event.

Always single-quote the path so the shell doesn't try to expand `&`, spaces, or other metacharacters:

```bash
python3 /Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_content.py '/path/to/article.md'
```

For a Notion-sourced article, that path is `/tmp/zsxq-notion/article.md`.

If the path is a directory (common for Notion exports), the script auto-selects the lone `.md` file, or lists options when there are multiple. The JSON summary it prints to stdout is the source of truth for the rest of the run:

```json
{
  "title": "My Article Title",
  "source_file": "/path/to/dir/article.md",
  "content_chars": 5432,
  "js_file": "/tmp/zsxq_paste_content.js",
  "images": [
    {"index": 1, "marker": "[[IMG_1]]", "src": "img1.png", "resolved_path": "/path/to/dir/img1.png"}
  ]
}
```

Hold on to `title` for the title-fill step and `images` for the image pipeline.

### Switch the editor to Markdown mode

Pasting Markdown into Quill leaves the hash signs and asterisks as literal text. Switch to Milkdown first. Use JS rather than `find text` because several buttons share similar labels:

```bash
agent-browser --session-name zsxq eval '(() => {
  const hasPM = !!document.querySelector(".ProseMirror");
  const hasQuill = !!document.querySelector(".ql-editor");
  const toggleText = document.querySelector(".toggle-mode")?.textContent?.trim() || "";
  if (!hasPM && hasQuill && toggleText.includes("Markdown")) {
    document.querySelector(".toggle-mode")?.click();
    setTimeout(() => document.querySelector(".confirm")?.click(), 500);
  }
  return { hasPM, hasQuill, toggleText };
})()'

agent-browser wait 2000
agent-browser --session-name zsxq eval '!!document.querySelector(".ProseMirror")'
```

The last check must return `true` before moving on.

### Dismiss the restore-draft popup if it appears

After switching modes (or on a fresh load), Zsxq sometimes offers to "恢复上次编辑的内容". Clicking it would wipe the fresh content you're about to paste. Dismiss it by matching the exact text `忽略`:

```bash
agent-browser --session-name zsxq eval '(() => {
  const btn = Array.from(document.querySelectorAll("button, .cancel, .btn")).find(
    el => el.textContent && el.textContent.trim() === "忽略"
  );
  if (btn) { btn.click(); return "dismissed"; }
  return "no popup";
})()'
```

If the element isn't found, no popup is on screen. Move on.

### Fill the title

Snapshot to find the ref, then fill. The title input is keyed by its placeholder:

```bash
agent-browser --session-name zsxq snapshot -i
agent-browser --session-name zsxq find placeholder "请在这里输入标题" fill "<TITLE FROM STEP 1>"
```

### Paste the body

Dispatch the JS file that `prepare_content.py` wrote. This fires the synthetic paste event that Milkdown intercepts and parses as Markdown:

```bash
agent-browser --session-name zsxq eval "$(cat /tmp/zsxq_paste_content.js)"
```

Don't use `fill` or `type` here — those bypass the paste handler, leaving raw Markdown on the page.

Verify the body was inserted:

```bash
agent-browser --session-name zsxq eval 'document.querySelector(".ProseMirror")?.textContent?.length || 0'
```

A non-zero length means the paste took.

## Image pipeline

Skip this entire section when `prepare_content.py` reported an empty `images` array.

For each image in order, run three commands: delete the placeholder marker, wait for ProseMirror to sync its internal selection, then paste the image. They must be three separate calls — combining them causes images to land at the wrong cursor position. The reason is explained in [`references/editor-internals.md`](references/editor-internals.md#why-image-insertion-has-to-be-three-separate-eval-calls).

Before the loop, generate the paste JS for each image:

```bash
python3 /Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_image.py '<resolved_path>'
```

Then, for each marker (e.g. `[[IMG_1]]`, `[[IMG_10]]`), run this three-step sequence. Replace both occurrences of `[[IMG_N]]` in command 1 with the real marker string; the length is derived from the string itself, so double- and triple-digit indices work:

```bash
# 1. Delete the marker at its position
agent-browser --session-name zsxq eval '(() => {
  const marker = "[[IMG_N]]";
  const mlen = marker.length;
  const e = document.querySelector(".ProseMirror");
  const v = e?.pmViewDesc?.view;
  if (v) {
    let p = -1;
    v.state.doc.descendants((n, pos) => {
      if (p !== -1) return false;
      if (n.isText && n.text && n.text.includes(marker)) { p = pos + n.text.indexOf(marker); return false; }
    });
    if (p !== -1) { v.dispatch(v.state.tr.delete(p, p + mlen)); v.focus(); return {ok:true, method:"pm", pos:p}; }
  }
  const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const i = w.currentNode.textContent.indexOf(marker);
    if (i !== -1) {
      const r = document.createRange(); r.setStart(w.currentNode, i); r.setEnd(w.currentNode, i + mlen);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); r.deleteContents();
      return {ok:true, method:"dom"};
    }
  }
  return {ok:false, error:"marker not found"};
})()'

# 2. Let ProseMirror catch up
agent-browser wait 500

# 3. Paste the image
agent-browser --session-name zsxq eval "$(cat /tmp/zsxq_paste_image.js)"
```

After each image, verify and give the upload time to resolve:

```bash
agent-browser wait 3000
agent-browser --session-name zsxq eval 'document.querySelectorAll(".ProseMirror img:not(.ProseMirror-separator)[src]").length'
```

If `resolved_path` was `null` for an image in the JSON summary, the content pipeline couldn't find the file on disk. Skip that image, warn the user, and continue — there's no safe way to guess.

## Publish pipeline

### Schedule the publish for tomorrow 10:00

A scheduled post behaves like a draft until its scheduled time — the user can still open it, edit it, or cancel it from "我的文章". There's no need to click "保存" first: scheduling is itself the save.

Setting a scheduled publish time mutates the publish button: its text changes from `发布` to `定时发布`. Never click it while it still says `发布` — that posts instantly, which the skill must never do.

Enable the schedule toggle first:

```bash
agent-browser --session-name zsxq click ".scheduled-topic-timer label.green"
agent-browser wait 1000
```

Then set tomorrow's date and pick 10:00 from the hour/minute lists. flatpickr owns the date input, so we go through its instance:

```bash
agent-browser --session-name zsxq eval '(() => {
  const tomorrow = new Date(Date.now() + 86400000);
  const y = tomorrow.getFullYear();
  const m = String(tomorrow.getMonth() + 1).padStart(2, "0");
  const d = String(tomorrow.getDate()).padStart(2, "0");
  const dateStr = y + "/" + m + "/" + d;
  const hour = "10";
  const minute = "00";
  const input = document.querySelector(".scheduled-topic-timer #date.flatpickr-input");
  const fp = input?._flatpickr;
  if (!fp) return { ok: false, reason: "flatpickr not found" };
  fp.setDate(dateStr, true, "Y/m/d");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  const boxes = [...document.querySelectorAll(".scheduled-topic-timer app-topic-timer .time")];
  if (boxes.length < 2) return { ok: false, reason: "time boxes not found" };
  const pick = (box, val) => {
    const hit = [...box.querySelectorAll("li")].find(li => li.textContent.trim() === val);
    if (hit) { hit.click(); return val; }
    const first = box.querySelector("li");
    if (first) { first.click(); return first.textContent.trim(); }
    return null;
  };
  const h = pick(boxes[0], hour);
  const mi = pick(boxes[1], minute);
  const postText = document.querySelector(".operation-btns .post.btn")?.textContent?.trim() || "";
  return { ok: true, date: input.value, hour: h, minute: mi, postText, scheduled: dateStr + " " + h + ":" + mi };
})()'
```

Confirm the button text flipped, then submit:

```bash
agent-browser --session-name zsxq eval 'document.querySelector(".operation-btns .post.btn")?.textContent?.trim()'
# Expected: "定时发布". If it still says "发布", re-toggle the schedule switch and re-run the date setter.

agent-browser --session-name zsxq click ".operation-btns .post.btn"
agent-browser wait 2000
```

Report back to the user:

```
✅ 已设置定时发布：明天 YYYY/MM/DD 10:00。请在"我的文章"中确认。
```

## Invariants

These are the things that, if violated, quietly break the skill in ways that are hard to diagnose:

- **Always run `agent-browser close --all` once at the start.** Mixing a leftover headless daemon with a new headed session is the most common confusing failure.
- **Never click the publish button while it reads `发布`.** That publishes instantly. The only safe path is: schedule first, confirm the button text flipped to `定时发布`, then click.
- **Always go through the helper scripts for content and image pasting.** Constructing JS inline in the shell is a well of subtle escaping bugs.
- **For Notion sources, always localize images before paste.** Zsxq's Milkdown only ingests images via binary paste; remote URLs in the Markdown body will render as broken links.
- **Do not modify the original source.** Never write back to the user's local Markdown file, and never edit the Notion page. All transformations happen in `/tmp/zsxq-notion/` or similar scratch directories.

## See also

- [`references/troubleshooting.md`](references/troubleshooting.md) — recovery steps for the failures that actually happen in practice.
- [`references/editor-internals.md`](references/editor-internals.md) — Quill vs Milkdown, the element reference table, and why the image pipeline is three commands instead of one.
