---
name: format-platform-article
description: Convert a local Markdown article and media folder into a WeChat-first multi-platform publish package. Use this skill after notion-to-md exports Markdown/media and before publishing to WeChat Official Account, Zhihu, Toutiao, Zsxq, SMZDM, or similar rich-text article platforms. Generates wechat.html, preview.html, copy.html, platform Markdown variants, assets, and report.json. Does not fetch Notion, log into platforms, copy to clipboard, or publish.
---

# Format Platform Article

Use this skill to turn a local Markdown article into a portable publish package for multiple Chinese content platforms.

## When To Use

- The source is already a local Markdown file.
- Images are local files beside the Markdown or under a local media folder.
- The user wants a good-looking WeChat Official Account version plus safer files for Zhihu, Toutiao, Zsxq, or SMZDM.
- The user wants formatting output before any browser publishing automation.

## Boundaries

This skill does not fetch Notion pages, upload images, write to the system clipboard, log into websites, create drafts, or publish posts.

Use `notion-to-md` first when the source is a Notion URL. Use `markdown-table-images` directly when the only request is table image conversion.

## Default Workflow

1. Identify the local Markdown file.
2. Choose an output directory. Default to `<article-stem>.publish` beside the source file.
3. Run the builder:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish
```

4. Open `preview.html` and inspect the WeChat rendering.
5. Check `report.json` for warnings before handing files to platform publishing skills.

## Output

```text
article.publish/
├── wechat.html
├── preview.html
├── copy.html
├── platforms/
│   ├── zhihu.md
│   ├── toutiao.md
│   ├── zsxq.md
│   └── smzdm.md
├── assets/
└── report.json
```

## Options

- `--overwrite`: replace an existing publish package.
- `--strict`: fail if compatibility warnings are detected.
- `--table-mode auto|always|never`: control table image conversion. Use `auto` by default.
- `--style magazine`: first-version default. Other styles are intentionally rejected until implemented.

## Error Handling

Fail on missing source files, missing local images, and output directory conflicts. Warn on remote images, large images, risky raw HTML, and table conversion failures unless `--strict` is set.
