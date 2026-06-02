---
name: format-platform-article
description: Convert a local Markdown article and media folder into a WeChat-first multi-platform publish package. Use this skill after notion-to-md exports Markdown/media and before publishing to WeChat Official Account, Zhihu, Toutiao, Zsxq, SMZDM, or similar rich-text article platforms. Generates paste-ready HTML files (WeChat/Toutiao/Zsxq/SMZDM), an import-ready Zhihu Markdown via md2zhihu, local assets, an image fallback manifest, and report.json. You must use this skill whenever the user wants to publish Markdown articles to Chinese social/tech media platforms, format posts for WeChat/Zhihu/Toutiao/Zsxq/SMZDM, or build a publish package from a Markdown file, even if they don't explicitly ask for a "publish package".
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

Zhihu output is produced by delegating to the [`md2zhihu`](https://github.com/drmingdrmer/md2zhihu) CLI, which converts the article into a single import-ready `platforms/zhihu.md` and (when a Git asset repo is supplied) pushes images there as HTTPS URLs. md2zhihu is optional: when the binary or asset repo is missing, the build degrades to a local-link `zhihu.md` and records a warning. A failed conversion must not block package generation.

## Default Workflow

1. Identify the local Markdown file.
2. Choose an output directory. Default to `<article-stem>.publish` beside the source file.
3. (One-time, only if Zhihu publishing is needed.) Install the md2zhihu toolchain and prepare a Git asset repo for images. md2zhihu shells out to Pandoc, ImageMagick, and the mermaid CLI to rasterize LaTeX/mermaid/graphviz, then pushes images to a Git repo and rewrites them to raw HTTPS URLs. **md2zhihu does not support Windows.**

```bash
brew install pandoc imagemagick node        # macOS; Pandoc + ImageMagick + Node
npm install -g @mermaid-js/mermaid-cli       # mermaid -> image (mmdc)
uv tool install md2zhihu --with pygments --with urllib3 --with requests --with mistune  # the converter CLI
```

   Create an empty public repo you have push access to (GitHub or Gitee) to use as an image bed, e.g. `https://github.com/backtomyfuture/images.git`. Provide it to the build via `--zhihu-asset-repo` or the `ZHIHU_ASSET_REPO` env var. A branch suffix is supported (`...repo.git@master`).

4. Run the builder. It produces `platforms/zhihu.md` (Zhihu import format) plus the paste-ready HTML for the other platforms, and opens `platforms/zhihu.md` when done:

```bash
ZHIHU_ASSET_REPO="https://github.com/backtomyfuture/images.git" \
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish \
  --overwrite
```

5. In Zhihu's web editor open a new article, click the `···` / `导入` menu, and choose **导入文档** to import `platforms/zhihu.md` (or paste its Markdown if your account exposes the Markdown paste mode). The hosted HTTPS images render inline; the title field is separate.
6. Check `report.json` for warnings (e.g. `md2zhihu_not_installed`, `zhihu_asset_repo_missing`, `zhihu_md2zhihu_failed`) before handing files to platform publishing skills. When md2zhihu or the repo is unavailable, `zhihu.md` falls back to local `../assets/` links and you upload images manually using `image-manifest.md`.

To inspect a different platform first, pass `--open-target wechat|zhihu|toutiao|zsxq|smzdm`. Use `--no-open` to disable the auto-open behaviour entirely.

## Output

```text
article.publish/
├── wechat.html
├── image-manifest.md          # emitted when the article has local images
├── platforms/
│   ├── zhihu.md               # md2zhihu import format (HTTPS or local-link images)
│   ├── toutiao.html
│   ├── zsxq.html
│   └── smzdm.html
├── assets/
└── report.json
```

Do not expect legacy intermediate files such as `preview.html`, `copy.html`, `wechat-placeholder.html`, platform Markdown fallbacks, `zhihu.html`, `zhihu-embedded.html`, `zhihu-remote.html`, `zhihu-image-map.*`, `platform-guide.md`, or `platform-report.json`.

## Core Formatting Rules

- Do not inject a visible article title, route card, reading-time hint, platform note, or generic lead paragraph into the body. Platform editors have separate title fields, and any intro must come from the source Markdown.
- Treat each primary HTML file as the body content to paste into the rich-text editor. Metadata inside the HTML `<title>` is fine, but the visible `<body>` should contain only the article body.
- Embed local images as Base64 by default for `wechat.html`, `platforms/toutiao.html`, `platforms/zsxq.html`, and `platforms/smzdm.html`.
- Do not use Base64 for Zhihu. Zhihu output is Markdown (`platforms/zhihu.md`) produced by md2zhihu: with a Git asset repo, images become `https://.../raw/...` URLs that Zhihu's importer accepts; without one, the Markdown keeps `../assets/` links for manual upload.
- Always copy local images into `assets/`. When local images exist, emit `image-manifest.md` so the user can manually re-upload images in order if md2zhihu/the asset repo is unavailable or another platform drops embedded images during paste.
- Preserve authored headings, paragraphs, links, bold/italic text, blockquotes, lists, images, and code blocks. Do not invent editorial framing.
- WeChat visual style should feel like a polished editorial column from a top-tier Chinese magazine account (e.g. 36氪, 晚点LatePost, 量子位). Concretely:
  - H2 is a chapter marker: bold dark heading prefixed by a small terracotta accent block (`#c2410c`) and followed by a thin warm hairline (`#ece4d6`) running across the column. No filled capsule, no heavy left bar, no all-caps.
  - H3 is a section subhead: bold dark text led by a `▍` accent in the brand color, with a soft amber underline (`#fde68a`) running only under the heading text. No dark-filled box.
  - Body paragraphs use `line-height:2.0` with generous bottom margin so the column breathes; the first paragraph is one step larger and uses the deepest text color as a lead-in.
  - **Bold** spans get the "highlighter marker" treatment — bold weight plus a 2px amber underline (`#fcd34d`) — so emphasized keywords pop without screaming. Links share the same treatment but in a deeper terracotta (`#9a3412`).
  - Markdown `>` quotes render as a warm cream card (`#fdf6ec`) with a Georgia serif open-quote glyph and italic body, framed by a 3px terracotta left rule. No heavy shadow.
  - Emoji-prefixed callouts (`⚠️ 💡 ✅ 🎯`) render as labeled cards with a small letter-spaced uppercase header (editorial style) above the body.
  - Tables get a zebra-striped warm body, an editorial cream header with a 2px terracotta underline, and a soft warm hairline frame with rounded corners.
  - Ordered lists use zero-padded monospace numerals (`01.`, `02.`) in the brand color; unordered lists use a small filled brand-color dot.
  - Code blocks live inside a warm cream card with a 3px terracotta accent rule, a small uppercase language label, and copy-safe `pre > code` whitespace handling. Inline `code` matches the warm palette.
  - Dividers render as a centered three-dot `● ● ●` in muted gold so they feel like an editorial pause, not a default `<hr>`.
  - All effects rely on inline `style` only (no `<style>` block, no classes, no CSS-only `::before`) so they survive paste into the WeChat editor.
- Render Markdown dividers (`---`, `***`, `___`) as real-character separators (the editorial three-dot `● ● ●` in muted gold for WeChat) rather than empty CSS-only rules. WeChat often strips blank `div`/`hr` separators during copy/paste, so a visible character-based mark is required. Avoid templated single em-dashes — they read as accidental punctuation.
- When large Markdown tables are converted to PNGs, do not repeat the nearest heading as a pill caption under the image. The H2 already names the section; duplicated captions look like broken image labels in WeChat.
- Code blocks should preserve whitespace and use copy-safe `pre > code` structures. Full-width placeholders such as `【UUID】` and `【你的服务器IP】` should keep their visual cue.

## Platform Notes

- WeChat: use `wechat.html`. It is the main visual layout, embeds local images as Base64, and uses the magazine column heading/quote/callout treatment.
- Zhihu: use `platforms/zhihu.md`. It is generated by md2zhihu and imported via Zhihu's 导入文档 / Markdown paste flow. With `--zhihu-asset-repo` (or `$ZHIHU_ASSET_REPO`) the images are pushed to your Git repo and embedded as HTTPS URLs; LaTeX/mermaid/graphviz blocks are rasterized to images automatically. Without a repo or without md2zhihu installed, `zhihu.md` keeps local `../assets/` links — upload those in order using `image-manifest.md`.
- Toutiao: use `platforms/toutiao.html`. It is body-only and uses native rich-text structures with Base64 images.
- Zsxq: use `platforms/zsxq.html`. It is body-only and intentionally avoids the WeChat magazine wrapper/background. It uses paste-stable native tags plus the text-safe `▍` marker for authored high-value paragraphs.
- SMZDM: use `platforms/smzdm.html`. It is body-only and embeds local images as Base64. Convert product URLs to platform cards manually inside the editor.

## Options

- `--overwrite`: replace an existing publish package.
- `--strict`: fail if compatibility warnings are detected.
- `--table-mode auto|always|never`: control table image conversion. Use `auto` by default.
- `--style magazine`: first-version default. Other styles are intentionally rejected until implemented.
- `--zhihu-asset-repo <git-url>`: Git repo md2zhihu pushes Zhihu images to and rewrites as raw HTTPS URLs, e.g. `https://github.com/backtomyfuture/images.git` or `git@github.com:backtomyfuture/images.git`. Defaults to `$ZHIHU_ASSET_REPO` / `$MD2ZHIHU_ASSET_REPO`. Without it, `zhihu.md` keeps local `../assets/` links.
- `--md2zhihu-bin /path/to/md2zhihu`: explicit path to the md2zhihu executable. Defaults to the one found on `PATH`.
- `--no-zhihu-download`: tell md2zhihu not to fetch remote `http(s)` image URLs while converting (it downloads and re-hosts them by default).
- `--no-download-remote-images`: skip downloading remote (`http(s)`) Markdown images into `assets/`. By default the build fetches every remote URL (including Notion S3 presigned URLs that expire within an hour) so the cross-platform HTML files keep working after the original URL dies. Disable only if you know the remote URLs are stable and you want zero outbound traffic.
- `--open` (default) / `--no-open`: auto-open the chosen platform output in the system browser after build, so you can copy + paste directly.
- `--open-target zhihu|wechat|toutiao|zsxq|smzdm`: which output to auto-open. Defaults to `zhihu`, which opens `platforms/zhihu.md` for import.

## Zhihu via md2zhihu

Zhihu output delegates to the [`md2zhihu`](https://github.com/drmingdrmer/md2zhihu) CLI (`scripts/zhihu_md2zhihu.py` is a thin wrapper). The build snapshots the Zhihu source Markdown *before* any table→PNG conversion so md2zhihu renders native tables, then runs:

```bash
md2zhihu <source.md> -o platforms/zhihu.md -p zhihu --download \
  -r "https://github.com/backtomyfuture/images.git"
```

md2zhihu requires Pandoc, ImageMagick, the mermaid CLI (`mmdc`), and a Git repo it can push to. It rasterizes LaTeX, mermaid, and graphviz blocks to images and rewrites every local/remote image to a raw HTTPS URL in the asset repo. **It does not run on Windows.**

Graceful degradation (each path emits a `report.json` warning and still ships a usable `zhihu.md`):

- md2zhihu not installed → `md2zhihu_not_installed`, local-link fallback.
- no asset repo configured → `zhihu_asset_repo_missing`, local-link fallback.
- conversion error / timeout → `zhihu_md2zhihu_failed`, local-link fallback.

> [!TIP]
> 如果源 Markdown 中包含已失效、过期或无法访问的远程图片链接（如过期的 Notion S3 预签名 URL 或占位地址），`md2zhihu` 默认会因下载失败而导致整个知乎转换中断并引发异常。此时可以配合使用 `--no-zhihu-download` 选项，强制跳过远程图片的下载与托管，保留原始链接继续完成其它内容的转换。

## Quality Checks

Before handing results to a publishing skill, verify:

- `wechat.html` and each `platforms/*.html` body does not contain an injected visible title, route card, platform note, or generic lead such as `先说价值` / `先说结论`.
- `wechat.html` keeps the editorial visual treatment for authored H2/H3 and Markdown quotes/callouts without requiring external CSS classes or a `<style>` block. H2 should be a clean left-rule title, not a rounded capsule.
- Markdown dividers are visible after paste because they use real separator characters, not CSS-only empty blocks.
- Generated table images do not show duplicate heading captions underneath.
- `platforms/zhihu.md` exists and is import-ready. When an asset repo + md2zhihu succeed it contains raw HTTPS image URLs (`report.json` → `zhihu.hosted: true`); otherwise it keeps `../assets/` links and `report.json` warns (`md2zhihu_not_installed` / `zhihu_asset_repo_missing` / `zhihu_md2zhihu_failed`). It must never contain `data:image/`.
- Local images exist in `assets/`, and `image-manifest.md` lists the manual upload order when images are present.
- Raw Markdown dividers such as `---` are rendered, list items are not collapsed into paragraphs, and code blocks preserve line breaks.
- `report.json` has no unexpected warnings before publishing.
