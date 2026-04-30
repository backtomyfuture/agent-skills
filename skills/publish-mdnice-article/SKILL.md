---
name: publish-mdnice-article
description: Publish or import an article into Markdown Nice (mdnice / editor.mdnice.com / markdown nice) from a local Markdown file or Notion-sourced Markdown. ALWAYS use this skill whenever the user mentions Markdown Nice, mdnice, editor.mdnice.com, 发布到 markdown nice, 发布到 mdnice, 新建 mdnice 文章, or asks to turn a Notion page / Markdown file / article note into a Markdown Nice draft. This skill logs into https://editor.mdnice.com/, creates a new article, fills the title, pastes Markdown into #nice-md-editor, handles images one by one, and relies on Markdown Nice autosave instead of publishing or explicitly saving.
---

# Publish Markdown Nice Article

Create a new article in Markdown Nice at `https://editor.mdnice.com/`, paste Markdown content into the editor, insert images, and let the site autosave. This skill does not publish anywhere; Markdown Nice is treated as an editing/staging platform.

The workflow is modeled after `publish-zsxq-article`, but the browser operations are different:

- Open Markdown Nice instead of Zsxq.
- Reuse the Zsxq Chrome profile if present, because the user asked to share the article-publishing browser profile.
- Click `#nice-md-editor`, create a new article, fill the modal title, confirm, then paste the body into `#nice-md-editor`.
- Do not click a save button. Markdown Nice autosaves.

## Prerequisites

- `agent-browser` CLI (`npm i -g agent-browser && agent-browser install`)
- Python 3 for the helper scripts in `scripts/`
- Optional: `Pillow` if large images need compression before synthetic paste

## Platform configuration

- **Editor URL:** `https://editor.mdnice.com/`
- **Primary editor selector:** `#nice-md-editor`
- **Preferred profile:** `~/.agent-browser/profiles/zsxq/`
- **Session name:** `mdnice`

Use the Zsxq profile by default if it exists. If it does not exist, open without a profile. If Markdown Nice redirects to login or shows an unauthenticated state, ask the user to log in manually in the headed browser, then continue from the same browser session.

## Helper scripts

All scripts live in this skill's `scripts/` directory. Use absolute paths:

- `/Users/jarod/.agents/skills/publish-mdnice-article/scripts/notion_ingest.py` — localizes remote Notion images and rewrites image references into local files.
- `/Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_content.py` — extracts the title, replaces image references with `[[IMG_N]]` placeholders, and writes `/tmp/mdnice_paste_content.js`. It writes through the Markdown Nice CodeMirror instance when available.
- `/Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_title.py` — writes `/tmp/mdnice_fill_title.js` to fill the new-article modal title and click confirm without shell quoting bugs.
- `/Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_image.py` — base64-encodes one image and writes `/tmp/mdnice_paste_image.js`.

## Windows notes

PowerShell 5 and Windows command-line limits need extra care:

- The helper scripts read Markdown as `utf-8-sig` and write JSON as UTF-8, so a UTF-8 BOM will not leak into the article title/body as `锘`.
- `prepare_content.py` normalizes local image links written as `![](<./media/image.png>)` before resolving files.
- Do not pass JS containing Chinese text directly as a raw Windows command argument. For content/title paste, use `agent-browser eval -b` with UTF-8 base64.
- Large images can make `mdnice_paste_image.js` too large for a Windows command line. `prepare_image.py` detects this and compresses through Pillow or a PowerShell `System.Drawing` fallback before writing the paste JS. If both fail, install Pillow with `python -m pip install Pillow`.

## Workflow

Run these phases in order:

1. **Pre-flight** — close stale browser sessions, open Markdown Nice, and confirm the editor is available.
2. **Content pipeline** — prepare Markdown, create a new article, fill the title, and paste the body into `#nice-md-editor`.
3. **Image pipeline** — for each extracted image, delete its marker and paste the binary image at that position.
4. **Autosave verification** — wait for Markdown Nice to autosave and report the article title back to the user.

## Pre-flight

### Close leftover sessions

Run this once at the start:

```bash
agent-browser close --all
```

### Open Markdown Nice

Prefer the shared Zsxq profile if present:

```bash
ls ~/.agent-browser/profiles/zsxq/ 2>/dev/null && echo "PROFILE_FOUND"
```

With profile:

```bash
agent-browser --headed true --session-name mdnice --profile ~/.agent-browser/profiles/zsxq/ open "https://editor.mdnice.com/"
```

Windows profile path:

```powershell
agent-browser --headed true --session-name mdnice --profile "$env:USERPROFILE\.agent-browser\profiles\zsxq" open "https://editor.mdnice.com/"
```

Without profile:

```bash
agent-browser --headed true --session-name mdnice open "https://editor.mdnice.com/"
```

Confirm the editor exists:

```bash
agent-browser wait 3000
agent-browser --session-name mdnice eval '(() => ({ url: location.href, hasEditor: !!document.querySelector("#nice-md-editor") }))()'
```

If `hasEditor` is false, take a snapshot and check whether the user must log in:

```bash
agent-browser --session-name mdnice snapshot -i
```

Ask the user to finish login manually in the headed browser. After they confirm, rerun the editor check once.

## Content pipeline

### If the source is a Notion URL

Fetch the page with the available Notion tool, extract the author-written Markdown body, and write it to `/tmp/mdnice-notion/raw.md`. Then localize images:

```bash
mkdir -p /tmp/mdnice-notion
python3 /Users/jarod/.agents/skills/publish-mdnice-article/scripts/notion_ingest.py \
  --input /tmp/mdnice-notion/raw.md \
  --output-dir /tmp/mdnice-notion
```

If the script reports failed image downloads, stop and ask whether to refetch the page or skip the missing images. Continue with `/tmp/mdnice-notion/article.md`.

### Prepare the Markdown

Always single-quote source paths because article folders often contain spaces or `&`:

```bash
python3 /Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_content.py '/path/to/article.md'
```

The JSON summary is the source of truth:

```json
{
  "title": "Article Title",
  "source_file": "/path/to/article.md",
  "content_chars": 5432,
  "js_file": "/tmp/mdnice_paste_content.js",
  "images": [
    {"index": 1, "marker": "[[IMG_1]]", "src": "img.png", "resolved_path": "/path/to/img.png"}
  ]
}
```

Hold on to `title` and the `images` array.

### Create a new article

Click the editor once, then click the new-article control by text. If text lookup fails, inspect with `snapshot -i` and use the visible control reference.

```bash
agent-browser --session-name mdnice click "#nice-md-editor"
agent-browser wait 500
agent-browser --session-name mdnice find text "新建文章" click
agent-browser wait 1000
```

Fill the title in the modal input and confirm. Generate a JS file so titles with quotes or shell metacharacters do not break the command:

```bash
python3 /Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_title.py '<TITLE FROM SUMMARY>'
agent-browser --session-name mdnice eval "$(cat /tmp/mdnice_fill_title.js)"
agent-browser wait 1000
```

On Windows/PowerShell:

```powershell
python C:\Users\<you>\.agents\skills\publish-mdnice-article\scripts\prepare_title.py '<TITLE FROM SUMMARY>'
$js = Get-Content -Raw -Encoding UTF8 -Path "C:\tmp\mdnice_fill_title.js"
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($js))
agent-browser --session-name mdnice eval -b $b64
```

The helper prefers the Ant Design input whose placeholder is `请输入标题`, then falls back to an input near `文章标题`, then to older selectors. This avoids filling the folder input by mistake. If it still fails because Ant Design changed the modal structure, inspect the current page:

```bash
agent-browser --session-name mdnice eval '(() => {
  const modal = [...document.querySelectorAll(".ant-modal-content")].find(el => el.offsetParent !== null);
  const input = modal?.querySelector(".ant-modal-body input");
  return { hasModal: !!modal, hasInput: !!input };
})()'
```

Then use the current snapshot refs to fill the visible input and click the primary modal button.

### Paste the body

Paste via the generated JS file:

```bash
agent-browser --session-name mdnice eval "$(cat /tmp/mdnice_paste_content.js)"
```

On Windows/PowerShell, use UTF-8 base64 to avoid mojibake:

```powershell
$js = Get-Content -Raw -Encoding UTF8 -Path "C:\tmp\mdnice_paste_content.js"
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($js))
agent-browser --session-name mdnice eval -b $b64
```

Verify content length:

```bash
agent-browser --session-name mdnice eval '(() => {
  const e = document.querySelector("#nice-md-editor");
  const value = e && ("value" in e ? e.value : e.textContent);
  return { length: (value || "").length, url: location.href };
})()'
```

If this returns a short length even though the paste step returned success, query the CodeMirror instance directly:

```bash
agent-browser --session-name mdnice eval '(() => {
  const cm = document.querySelector(".CodeMirror")?.CodeMirror;
  const value = cm?.getValue?.() || "";
  return { length: value.length, markerCount: (value.match(/\[\[IMG_\d+\]\]/g) || []).length };
})()'
```

A non-zero CodeMirror length means the paste took. If the body appears as raw Markdown, that is expected for Markdown Nice; it is the Markdown editor.

## Image pipeline

Skip this section when `prepare_content.py` reports an empty `images` array.

Markdown Nice can re-render the editor while it autosaves. Process each marker in order and keep the delete/wait/paste sequence separate.

Prepare each image:

```bash
python3 /Users/jarod/.agents/skills/publish-mdnice-article/scripts/prepare_image.py '<resolved_path>'
```

On Windows, large screenshots are compressed automatically when the base64 payload would exceed the command-line-safe threshold:

```powershell
python C:\Users\<you>\.agents\skills\publish-mdnice-article\scripts\prepare_image.py '<resolved_path>' --max-size 900
```

If the script reports that both Pillow and PowerShell compression failed, install Pillow:

```powershell
python -m pip install Pillow
```

Delete the marker and leave the cursor at that position:

```bash
agent-browser --session-name mdnice eval '(() => {
  const marker = "[[IMG_N]]";
  const cm = document.querySelector(".CodeMirror")?.CodeMirror;
  if (cm) {
    const value = cm.getValue();
    const start = value.indexOf(marker);
    if (start === -1) return { ok: false, error: "marker not found" };
    const from = cm.posFromIndex(start);
    const to = cm.posFromIndex(start + marker.length);
    cm.replaceRange("", from, to);
    cm.setCursor(from);
    cm.focus();
    if (typeof cm.save === "function") cm.save();
    return { ok: true, method: "codemirror", pos: start, line: from.line, ch: from.ch };
  }

  const editor = document.querySelector("#nice-md-editor");
  if (!editor) return { ok: false, error: "editor not found" };
  editor.focus();

  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const i = node.textContent.indexOf(marker);
    if (i !== -1) {
      const r = document.createRange();
      r.setStart(node, i);
      r.setEnd(node, i + marker.length);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
      r.deleteContents();
      return { ok: true, method: "dom" };
    }
  }
  return { ok: false, error: "marker not found" };
})()'
```

Wait, then paste the image:

```bash
agent-browser wait 500
agent-browser --session-name mdnice eval "$(cat /tmp/mdnice_paste_image.js)"
agent-browser wait 3000
```

If Windows still rejects the image paste command as too long, lower `--max-size` or `--max-inline-chars` and regenerate the image paste JS.

Verify the marker count is going down:

```bash
agent-browser --session-name mdnice eval '(() => {
  const e = document.querySelector("#nice-md-editor");
  const value = e && ("value" in e ? e.value : e.textContent);
  return (value.match(/\[\[IMG_\d+\]\]/g) || []).length;
})()'
```

If `resolved_path` is `null`, skip that image and warn the user; there is no safe path to infer the missing file.

## Autosave verification

Markdown Nice autosaves, so do not click a save button unless the user explicitly asks for a different behavior. After content and image insertion:

```bash
agent-browser wait 3000
agent-browser --session-name mdnice eval '(() => {
  const e = document.querySelector("#nice-md-editor");
  const value = e && ("value" in e ? e.value : e.textContent);
  return { url: location.href, hasEditor: !!e, length: (value || "").length };
})()'
```

Report back:

```text
已在 Markdown Nice 新建并填入文章：《TITLE》。平台会自动保存，请在 editor.mdnice.com 页面确认。
```

## Invariants

- Run `agent-browser close --all` once at the start.
- Prefer the shared `~/.agent-browser/profiles/zsxq/` profile, as requested by the user.
- Use `#nice-md-editor` as the primary editor target.
- Create the article before pasting the body; otherwise pasted content may modify whatever draft is currently open.
- Do not modify the original Markdown or Notion page. Temporary transforms belong in `/tmp/mdnice-notion/` or generated `/tmp/mdnice_*.js` files.
- Do not add a manual save step unless the user explicitly requests it; Markdown Nice autosaves.
