---
name: publish-xiaohongshu-article
description: Publish or stage an article/note to Xiaohongshu / RedNote / 小红书 from a local Markdown file, a Notion-sourced Markdown export, or a Notion page URL. ALWAYS use this skill whenever the user mentions 小红书, RedNote, rednote, xhs, xiaohongshu, 小红书笔记, 小红书长文, 创作服务平台, creator.xiaohongshu.com, 发小红书, 发布到小红书, or asks to turn a Notion page / Markdown file / article note into a Xiaohongshu post. This skill prepares title, body, topics, and local images, then uses the local `xiaohongshu-skills` CLI for post-login publishing actions. Login is user-managed through browser / agent-browser. Default to filling a draft/preview first; only click final publish when the user explicitly asks to publish now or schedule.
---

# Publish Xiaohongshu Article

Publish or stage content to Xiaohongshu's creator workflow. The source can be a local Markdown file, a directory containing one Markdown file plus images, or a Notion page that has first been fetched into Markdown.

Xiaohongshu is not a Markdown editor. Treat it as a social publishing surface: extract a short title, convert Markdown into plain note text, collect topics, resolve local images, and pass absolute paths to the post-login publishing backend.

## Operating Boundary

- **Login is out of scope.** The user manages login through browser / `agent-browser`. Do not run `login`, `get-qrcode`, `wait-login`, `phone-login`, `send-code`, `verify-code`, or `delete-cookies` from `xiaohongshu-skills`.
- You may run `check-login` once as a non-destructive readiness check. If it reports not logged in, stop and ask the user to complete login in their browser, then continue after they confirm.
- For publishing and staging, prefer the local `xiaohongshu-skills` CLI. Run it from its own directory with `uv run python scripts/cli.py <subcommand>`.
- Do not use Xiaohongshu MCP servers, Go tools, or other external publishing implementations for this skill. They cannot reliably stage a preview and they conflict with the local CLI boundary.
- Use `agent-browser` only for the user-managed login phase, live page inspection, or an explicit last-resort manual fallback requested by the user.

## Safety Defaults

- Default action is **fill and preview** or **save draft**, not final publish.
- Click final publish only when the user explicitly asks to publish now or schedule.
- Before final publish, summarize the title, body file, image count, topics, and schedule/original/visibility settings.
- Never modify the original Markdown or Notion page. Scratch files go under `/tmp/xhs-*`.
- Use absolute file paths for all source files, title/content files, images, and videos.
- Keep frequency low; repeated automated publishing can trigger Xiaohongshu risk controls.

## Prerequisites

- Python 3 for helper scripts in this skill.
- `uv` for running `xiaohongshu-skills`.
- A local clone/install of `xiaohongshu-skills`, ideally at `/Users/jarod/.agents/skills/xiaohongshu-skills`.
- Chrome with the `xiaohongshu-skills/extension` bridge installed and a logged-in Xiaohongshu session. The user handles that session separately.

## Helper Scripts

Use absolute paths:

- `/Users/jarod/.agents/skills/publish-xiaohongshu-article/scripts/notion_ingest.py` localizes remote Notion images and writes `/tmp/xhs-notion/article.md`.
- `/Users/jarod/.agents/skills/publish-xiaohongshu-article/scripts/prepare_note.py` converts Markdown into Xiaohongshu-ready files:
  - `/tmp/xhs_title.txt`
  - `/tmp/xhs_content.txt`
  - `/tmp/xhs_note_payload.json`

The prepared JSON is the source of truth:

```json
{
  "title": "20单位以内标题",
  "original_title": "Original Markdown H1",
  "mode": "note",
  "content_file": "/tmp/xhs_content.txt",
  "title_file": "/tmp/xhs_title.txt",
  "title_units": 18,
  "images": [
    {"index": 1, "resolved_path": "/abs/path/img_1.png"}
  ],
  "topics": ["AI", "效率工具"],
  "warnings": []
}
```

`title_units` follows the `xiaohongshu-skills` title rule: non-ASCII characters count as 1 unit, ASCII characters count as 0.5 unit rounded up. Keep normal note titles at 20 units or less.

## Workflow

Run these phases in order:

1. **Pre-flight**: locate `xiaohongshu-skills`, ensure dependencies, optionally check login readiness.
2. **Ingest**: if the source is Notion, fetch Markdown and localize images.
3. **Prepare**: run `prepare_note.py`, inspect `/tmp/xhs_note_payload.json`, and handle warnings.
4. **Stage**: use `fill-publish` for image notes or `long-article` for long articles.
5. **Publish or draft**: only publish if the user explicitly asked for final publish; otherwise leave preview open or save draft.
6. **Verify**: report title, image count, topics, mode, and final status.

## Pre-flight

### Locate `xiaohongshu-skills`

```bash
for p in \
  /Users/jarod/.agents/skills/xiaohongshu-skills \
  /Users/jarod/.codex/skills/xiaohongshu-skills \
  "$PWD/xiaohongshu-skills"; do
  test -f "$p/scripts/cli.py" && echo "$p"
done
```

If no directory is found, stop and tell the user that the local `xiaohongshu-skills` CLI is missing. Do not switch to a Xiaohongshu MCP backend. Use `agent-browser` for publishing only if the user explicitly asks for manual fallback.

### Ensure Dependencies

From the chosen directory:

```bash
cd '<XIAOHONGSHU_SKILLS_DIR>'
uv run python scripts/cli.py --help
```

If this fails due to missing Python packages, run:

```bash
uv sync
uv run python scripts/cli.py --help
```

### Optional Readiness Check

Do not perform login. Only verify readiness:

```bash
cd '<XIAOHONGSHU_SKILLS_DIR>'
uv run python scripts/cli.py check-login
```

If the JSON says `logged_in: false`, stop and ask the user to complete login with their browser / `agent-browser`. Continue only after the user says the logged-in browser session is ready.

Do not display returned QR codes, login links, or phone-login instructions from this skill. Those belong to the user's separate browser-managed login flow.

## Ingest

### Local Markdown

Use the file directly. If the user gives a directory, `prepare_note.py` auto-selects the lone `.md` file or asks for the exact file when there are multiple.

### Notion URL

If a Notion tool is available, fetch the page body as Markdown, strip connector wrappers, and write it to `/tmp/xhs-notion/raw.md`. Then run:

```bash
mkdir -p /tmp/xhs-notion
python3 /Users/jarod/.agents/skills/publish-xiaohongshu-article/scripts/notion_ingest.py \
  --input /tmp/xhs-notion/raw.md \
  --output-dir /tmp/xhs-notion
```

If `failed_count > 0`, stop and ask whether to re-fetch the Notion page or skip missing images. Signed Notion image URLs expire.

Continue with `/tmp/xhs-notion/article.md`.

## Prepare

Run:

```bash
python3 /Users/jarod/.agents/skills/publish-xiaohongshu-article/scripts/prepare_note.py '/abs/path/to/article.md'
```

Optional title and topics:

```bash
python3 /Users/jarod/.agents/skills/publish-xiaohongshu-article/scripts/prepare_note.py \
  '/abs/path/to/article.md' \
  --title '自定义标题' \
  --topic AI --topic 效率工具
```

Inspect `/tmp/xhs_note_payload.json` before publishing:

- If `warnings` mention missing images, do not silently skip them. Ask the user whether to proceed without those images or provide replacements.
- If `mode` is `long_article`, use the long article flow. Do not silently shorten the body into a normal note.
- If `mode` is `note` and `images` is empty, do not call `fill-publish`; Xiaohongshu image notes require at least one image. Ask for a cover/image or switch to long article mode if the user agrees.
- If the title was shortened, inspect `/tmp/xhs_title.txt`. If the title reads like a mechanical truncation, rewrite a natural replacement and rerun `prepare_note.py --title '...'` so the final title is still <= 20 `title_units`.

## Stage Normal Image Note

Use this for prepared payloads where `mode` is `note` and at least one image resolved.

```bash
cd '<XIAOHONGSHU_SKILLS_DIR>'
uv run python scripts/cli.py fill-publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images '/abs/path/img1.png' '/abs/path/img2.png' \
  --tags 'AI' '效率工具'
```

Optional flags supported by `xiaohongshu-skills`:

```bash
  --schedule-at '2026-04-29T12:00:00' \
  --original \
  --visibility '公开可见'
```

After `fill-publish`, report that the browser form is ready for review. Do not click final publish unless the user explicitly asked for it.

If the user explicitly asked to publish now or after a schedule preview:

```bash
uv run python scripts/cli.py click-publish
```

If the user cancels after the form has been filled, save a draft unless they explicitly ask to leave the browser form open:

```bash
uv run python scripts/cli.py save-draft
```

## Stage Long Article

Use this when the prepared payload says `mode: "long_article"` or the user explicitly asks for 小红书长文.

```bash
cd '<XIAOHONGSHU_SKILLS_DIR>'
uv run python scripts/cli.py long-article \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images '/abs/path/img1.png' '/abs/path/img2.png'
```

`--images` is optional for long article mode. The command fills the long article editor and triggers layout. If the JSON returns a `templates` list, present it to the user and choose only after they respond:

```bash
uv run python scripts/cli.py select-template --name '模板名'
```

Then move to the publish page and fill the description. Use `/tmp/xhs_content.txt`; the CLI truncates the description as needed:

```bash
uv run python scripts/cli.py next-step \
  --content-file /tmp/xhs_content.txt
```

Only after the user explicitly confirms final publication:

```bash
uv run python scripts/cli.py click-publish
```

If they cancel after staging, use `save-draft` unless they explicitly ask to leave the browser form open.

## Browser Fallback

This is not the default. Use browser UI automation only when:

- The user explicitly asks to handle the publish form manually with `agent-browser`; or
- `xiaohongshu-skills` is missing/broken and the user accepts the manual fallback.

Before typing or uploading anything, inspect the live DOM:

```bash
agent-browser --session-name xhs eval '(() => ({
  url: location.href,
  inputs: [...document.querySelectorAll("input, textarea")].map((e, i) => ({
    i,
    type: e.type || e.tagName,
    placeholder: e.placeholder || "",
    aria: e.getAttribute("aria-label") || ""
  })),
  buttons: [...document.querySelectorAll("button")].map(b => b.textContent.trim()).filter(Boolean).slice(0, 30),
  fileInputs: document.querySelectorAll("input[type=file]").length
}))()'
```

Use visible placeholders and snapshot refs instead of hard-coded selectors. Upload images through the current `agent-browser` file upload workflow from:

```bash
agent-browser skills get core --full
```

If the installed `agent-browser` cannot upload files, stop and return to the `xiaohongshu-skills` CLI path. Do not fake file input values with JavaScript because browsers block that for security.

Never click `发布`, `立即发布`, or similar final buttons in browser fallback unless the user explicitly asked for final publish.

## Verification

Before reporting completion:

- Parse the CLI JSON output and report `success`, `status`, or `error`.
- Verify the staged title equals `/tmp/xhs_title.txt` or report any mismatch.
- Verify body length is non-zero and the backend accepted `/tmp/xhs_content.txt`.
- Verify uploaded/staged image count equals `payload.images[*].resolved_path`; list skipped or missing images.
- Verify topics/tags were passed to `--tags` when supported by the selected flow.
- If final publish was clicked, verify the CLI returned success or the UI shows success.
- If draft/preview only, state clearly that final publish was not clicked.

## Failure Handling

- **Not logged in:** stop and ask the user to finish login in browser / `agent-browser`; do not run login commands.
- **CLI missing:** report the missing `xiaohongshu-skills` directory and ask whether to install/fix it or use explicit browser fallback.
- **Dependencies missing:** run `uv sync` inside `xiaohongshu-skills`, then retry `uv run python scripts/cli.py --help`.
- **Bridge extension disconnected:** ask the user to open Chrome and ensure the XHS Bridge extension is installed/enabled; then retry the CLI command.
- **Image missing:** stop for approval before proceeding without it.
- **No image for normal note:** ask for a cover/image or switch to long article mode with confirmation.
- **Content too long:** use long article mode or ask whether to shorten. Do not silently truncate the body.
- **Final publish unavailable:** leave the filled form open or save draft, then report that manual confirmation is needed.
