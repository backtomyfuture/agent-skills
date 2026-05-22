---
name: format-platform-article
description: Convert a local Markdown article and media folder into a WeChat-first multi-platform publish package. Use this skill after notion-to-md exports Markdown/media and before publishing to WeChat Official Account, Zhihu, Toutiao, Zsxq, SMZDM, or similar rich-text article platforms. Generates paste-ready HTML files, local assets, an image fallback manifest, and report.json. Does not fetch Notion, log into platforms, copy to clipboard, or publish.
---

# Format Platform Article

Use this skill to turn a local Markdown article into a portable publish package for Chinese content platforms.

## When To Use

- The source is already a local Markdown file.
- Images are local files beside the Markdown or under a local media folder.
- The user wants WeChat, Zhihu, Toutiao, Zsxq, or SMZDM paste-ready files before browser publishing automation.
- The user wants direct copy/paste output, with local assets preserved for manual image fallback.

## Boundaries

This skill does not fetch Notion pages, write to the system clipboard, log into websites, create drafts, or publish posts. Use `notion-to-md` first when the source is a Notion URL. Use `markdown-table-images` directly when the only request is table image conversion.

The builder may attempt optional Zhihu native image upload only when the user provides valid Zhihu cookies or a default cookie file exists. A failed optional upload must not block package generation.

## Default Workflow

1. Identify the local Markdown file.
2. Choose an output directory. Default to `<article-stem>.publish` beside the source file.
3. (One-time, only if Zhihu publishing is needed and `~/.zhihu-cli/cookies.json` does not yet contain `z_c0/_xsrf/d_c0`.) Capture Zhihu login cookies. **Reliable path: paste the Cookie request header from your real Chrome**, since `z_c0` is HttpOnly and Zhihu's anti-bot rejects Playwright/headless logins. In Chrome where you are already logged into Zhihu:

   - Press `Cmd+Opt+I` → Network tab → `Cmd+R` to reload → click any `zhihu.com` request → Headers → Request Headers → right-click the `Cookie:` value → Copy value.
   - Then run:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/zhihu_login.py \
  --cookie "<paste full cookie string here>" --force
```

The script parses the string, verifies `z_c0`/`_xsrf`/`d_c0` are present, and writes `~/.zhihu-cli/cookies.json` (chmod 600). You can also set the `ZHIHU_COOKIE` env var instead of `--cookie`. There is also an experimental headed-browser mode (`zhihu_login.py` with no args, uses `agent-browser`) but Zhihu currently blocks Playwright logins with `参数异常，请升级客户端重试`, so prefer the paste mode.

4. Run the builder. By default it auto-uploads images to Zhihu (when cookies are available) and pops the Zhihu HTML file in your browser when done:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish \
  --overwrite
```

5. In the auto-opened browser window, hit `Cmd+A` then `Cmd+C` to copy the Zhihu body, paste it into the Zhihu article editor (the title field is separate), and verify the images render in place.
6. Check `report.json` for warnings before handing files to platform publishing skills.

To inspect a different platform first, pass `--open-target wechat|zhihu|toutiao|zsxq|smzdm`. Use `--no-open` to disable the auto-open behaviour entirely.

## Output

```text
article.publish/
├── wechat.html
├── image-manifest.md          # emitted when the article has local images
├── platforms/
│   ├── zhihu.html
│   ├── toutiao.html
│   ├── zsxq.html
│   └── smzdm.html
├── assets/
└── report.json
```

Do not expect legacy intermediate files such as `preview.html`, `copy.html`, `wechat-placeholder.html`, platform Markdown fallbacks, `zhihu-embedded.html`, `zhihu-remote.html`, `platform-guide.md`, or `platform-report.json`.

## Core Formatting Rules

- Do not inject a visible article title, route card, reading-time hint, platform note, or generic lead paragraph into the body. Platform editors have separate title fields, and any intro must come from the source Markdown.
- Treat each primary HTML file as the body content to paste into the rich-text editor. Metadata inside the HTML `<title>` is fine, but the visible `<body>` should contain only the article body.
- Embed local images as Base64 by default for `wechat.html`, `platforms/toutiao.html`, `platforms/zsxq.html`, and `platforms/smzdm.html`.
- Do not use Base64 for Zhihu. Historical real-editor checks showed Zhihu displays `图片导入失败，请重新上传`; `platforms/zhihu.html` must use HTTPS image URLs produced by Zhihu upload/API or clear placeholders.
- Always copy local images into `assets/`. When local images exist, emit `image-manifest.md` so the user can manually re-upload images in order if Zhihu upload is unavailable or another platform drops embedded images during paste.
- Preserve authored headings, paragraphs, links, bold/italic text, blockquotes, lists, images, and code blocks. Do not invent editorial framing.
- WeChat visual style should feel like a polished editorial column: H2 uses a clean black text heading with a warm left rule (not a rounded capsule), H3 uses a compact filled heading band, and Markdown blockquotes/callouts use a warm tinted background with a left accent rule. Keep this styling inline and paste-stable for the WeChat editor.
- Render Markdown dividers (`---`, `***`, `___`) as very subtle real-character separators such as a faint centered `—`, not empty CSS-only rules or decorative dot groups. WeChat often strips blank `div`/`hr` separators during copy/paste, but heavy visible dividers feel templated.
- When large Markdown tables are converted to PNGs, do not repeat the nearest heading as a pill caption under the image. The H2 already names the section; duplicated captions look like broken image labels in WeChat.
- Code blocks should preserve whitespace and use copy-safe `pre > code` structures. Full-width placeholders such as `【UUID】` and `【你的服务器IP】` should keep their visual cue.

## Platform Notes

- WeChat: use `wechat.html`. It is the main visual layout, embeds local images as Base64, and uses the magazine column heading/quote/callout treatment.
- Zhihu: use `platforms/zhihu.html`. It is body-only, avoids wrapper headers and heavy CSS, and uses HTTPS image URLs only after `--zhihu-cookie-file` upload or `--remote-image-map` succeeds. Without uploaded URLs, `zhihu.html` intentionally shows image placeholders; use `image-manifest.md` and `assets/` to upload the images in order.
- Toutiao: use `platforms/toutiao.html`. It is body-only and uses native rich-text structures with Base64 images.
- Zsxq: use `platforms/zsxq.html`. It is body-only, uses paste-stable structures, and may use the text-safe `▍` marker for authored high-value paragraphs.
- SMZDM: use `platforms/smzdm.html`. It is body-only and embeds local images as Base64. Convert product URLs to platform cards manually inside the editor.

## Options

- `--overwrite`: replace an existing publish package.
- `--strict`: fail if compatibility warnings are detected.
- `--table-mode auto|always|never`: control table image conversion. Use `auto` by default.
- `--style magazine`: first-version default. Other styles are intentionally rejected until implemented.
- `--remote-image-map /path/to/map.json`: optional JSON map from generated asset paths to HTTPS image URLs. When supplied and complete, Zhihu output is rewritten into `platforms/zhihu.html` with remote HTTPS images.
- `--zhihu-cookie-file /path/to/cookies.json`: optional Zhihu cookie JSON file. Defaults to `~/.zhihu-cli/cookies.json` when present. If valid, the build attempts to upload local images to Zhihu and rewrite `zhihu.html` with HTTPS image URLs.
- `--no-zhihu-auto-upload`: skip optional Zhihu upload; `zhihu.html` will use image placeholders instead of Base64.
- `--open` (default) / `--no-open`: auto-open the chosen platform HTML in the system browser after build, so you can copy + paste directly.
- `--open-target zhihu|wechat|toutiao|zsxq|smzdm`: which HTML to auto-open. Defaults to `zhihu` since that is the only platform that requires uploaded images for paste-to-work.

Remote image map shape:

```json
{
  "../assets/image-1.png": "https://files.example.com/image-1.png",
  "../assets/image-2.png": "https://files.example.com/image-2.png"
}
```

## Optional Image Upload Helpers

Preferred automated path for Zhihu: let the builder batch-upload images to Zhihu's own image service, then rewrite `platforms/zhihu.html` with HTTPS image URLs. This uses Zhihu's web/internal upload flow, not an official public API, so keep the `assets/` + `image-manifest.md` fallback ready. It requires logged-in cookies `z_c0`, `_xsrf`, and `d_c0`.

**Cookie bootstrap (one-time):** run `scripts/zhihu_login.py` to capture cookies into `~/.zhihu-cli/cookies.json`. This is **not** the third-party `zhihu-cli` package — it is the helper shipped with this skill. Internally it drives `opencli browser` to read `document.cookie` from a logged-in Chrome session and writes a JSON dict file the builder picks up automatically. You can also bypass the browser with `--cookie "z_c0=...; _xsrf=...; d_c0=..."` (paste from DevTools → Application → Cookies → www.zhihu.com) or the `ZHIHU_COOKIE` env var.

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/zhihu_login.py
# or paste-mode:
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/zhihu_login.py \
  --cookie "z_c0=...; _xsrf=...; d_c0=..." --force
```

Once `~/.zhihu-cli/cookies.json` exists, every subsequent build auto-uploads images and emits a paste-ready `platforms/zhihu.html` with `https://*.zhimg.com/...` URLs. Failed uploads are now surfaced in `report.json` under the `zhihu_auto_upload_failed` warning instead of silently producing placeholders.

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish \
  --overwrite
```

Remote-map fallback: if images were uploaded by Markdown Nice or another HTTPS image host, provide a JSON map and rebuild with `--remote-image-map`.

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish \
  --overwrite \
  --remote-image-map /path/to/image-map.json
```

The bundled `upload_zhihu_images.py`, `upload_mdnice_images.py`, and `extract_remote_image_map.py` scripts are lower-level helpers for custom pipelines that already have a template map. They are not part of the default publish package output.

## Quality Checks

Before handing results to a publishing skill, verify:

- `wechat.html` and each `platforms/*.html` body does not contain an injected visible title, route card, platform note, or generic lead such as `先说价值` / `先说结论`.
- `wechat.html` keeps the editorial visual treatment for authored H2/H3 and Markdown quotes/callouts without requiring external CSS classes or a `<style>` block. H2 should be a clean left-rule title, not a rounded capsule.
- Markdown dividers are visible after paste because they use real separator characters, not CSS-only empty blocks.
- Generated table images do not show duplicate heading captions underneath.
- `platforms/zhihu.html` contains HTTPS image URLs when Zhihu upload/map succeeds; otherwise it contains explicit placeholders and `report.json` warns with `zhihu_image_upload_required`. It should not contain `data:image/`.
- Local images exist in `assets/`, and `image-manifest.md` lists the manual upload order when images are present.
- Raw Markdown dividers such as `---` are rendered, list items are not collapsed into paragraphs, and code blocks preserve line breaks.
- `report.json` has no unexpected warnings before publishing.
