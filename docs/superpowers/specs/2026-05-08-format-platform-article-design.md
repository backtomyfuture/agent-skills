# Format Platform Article Skill Design

Date: 2026-05-08
Status: approved for implementation planning

## Goal

Create a reusable skill named `format-platform-article` that turns a local Markdown article plus local media into a polished, platform-ready publish package. The first version optimizes the visual output for WeChat Official Account articles and provides conservative fallback Markdown files for Zhihu, Toutiao, Zsxq, and SMZDM.

This skill is an intermediate formatting layer. It does not fetch Notion pages, log into platforms, copy content to the clipboard, or publish posts. The expected upstream source is `notion-to-md` output such as `article.md` plus `media/`. The expected downstream consumers are a human editor or later platform-specific publishing skills.

## Research Basis

- `doocs/md` and Markdown Nice show that Markdown to styled WeChat-friendly rich text is a mature path for Chinese content publishing.
- The browser Clipboard API supports future rich-text copy flows, but the first version deliberately writes files only.
- WeChat Official Account draft APIs accept article content as an HTML-like `content` field, so keeping a clean, inline-styled HTML artifact is useful even before direct API publishing is implemented.
- Non-WeChat editors such as Zhihu, Toutiao, Zsxq, and SMZDM vary in how aggressively they sanitize rich HTML. The safer first-version strategy is platform-specific Markdown fallback files.

References:

- https://github.com/doocs/md
- https://github.com/mdnice/markdown-nice
- https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/write
- https://developers.weixin.qq.com/doc/offiaccount/Draft_Box/Add_draft.html

## Scope

In scope:

- Accept a local Markdown file as input.
- Resolve local image links relative to the Markdown file.
- Copy referenced local assets into a portable output directory.
- Generate a WeChat-first inline-styled HTML article.
- Generate a local preview page and a copy page placeholder for future clipboard automation.
- Generate conservative Markdown variants for Zhihu, Toutiao, Zsxq, and SMZDM.
- Convert publication-risky Markdown tables into images using the established `markdown-table-images` approach.
- Produce a machine-readable compatibility report.
- Provide deterministic tests and eval metadata.

Out of scope:

- Fetching Notion content directly.
- Uploading images to any platform.
- Writing to the system clipboard automatically.
- Logging into any website.
- Creating platform drafts or publishing posts.
- Running a local editor service like doocs/md or Markdown Nice.

## User-Confirmed Decisions

- Boundary: local Markdown and media input only.
- Main visual target: WeChat Official Account.
- Default visual style: magazine-column style, with stronger editorial spacing and pull-quote treatment than a plain technical document.
- Output shape: a publish package directory.
- Implementation approach: a local package generator, not an embedded third-party editor and not a platform publisher.

## Skill Interface

The skill directory will be:

```text
skills/format-platform-article/
├── SKILL.md
├── scripts/
│   └── build_publish_package.py
├── templates/
│   ├── wechat_magazine.html
│   └── preview.html
├── tests/
│   ├── fixtures/
│   │   ├── article.md
│   │   └── media/
│   └── test_build_publish_package.py
└── evals/
    └── evals.json
```

Primary command:

```bash
python3 skills/format-platform-article/scripts/build_publish_package.py article.md --output article.publish
```

Options:

- `--output DIR`: output publish package directory.
- `--overwrite`: allow replacing an existing output directory.
- `--strict`: fail when compatibility warnings are detected.
- `--table-mode auto|always|never`: control table image conversion. Default is `auto`.
- `--style magazine|technical|manual`: style entry point. The default is `magazine`; only `magazine` must be polished in the first version.

## Output Package

The default output directory is:

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

`wechat.html` is the main artifact. It should be usable for local inspection and future copy/API workflows. Styles must be inline or otherwise self-contained enough that the article body remains meaningful if pasted into an editor that strips classes.

`preview.html` wraps the article in a local preview frame with basic metadata and report links.

`copy.html` is a stable placeholder for a future rich-text copy flow. In the first version it can show the rendered article and a clear instruction that automatic clipboard copy is not implemented yet.

`platforms/*.md` files are conservative Markdown variants intended for manual paste or for downstream publishing skills.

`assets/` contains copied images and generated table images.

`report.json` is the source of truth for what happened during conversion.

## Conversion Rules

Title handling:

- Use the first H1 as the article title.
- If there is no H1, use the Markdown filename stem as the title and record a warning.
- Avoid duplicating the H1 in platform Markdown variants unless the target format needs it.

WeChat HTML:

- Use magazine-column spacing and a warm editorial palette.
- Render H2 and H3 as styled section headings.
- Render blockquotes as editorial pull quotes.
- Render code blocks with readable monospace styling and horizontal overflow protection.
- Render links visibly without relying only on color.
- Keep all style decisions local to the generated artifact.

Images:

- Resolve relative image paths from the source Markdown location.
- Copy local images into `assets/`.
- Preserve image order and position.
- Fail if a local image reference is missing.
- Keep remote images in the output only with a warning; do not download remote images in the first version.
- Warn on very large images.

Tables:

- By default, convert publication-risky Markdown pipe tables into PNG images.
- Reuse the visual direction and threshold logic from `markdown-table-images`: publication-style table images, not raw spreadsheet screenshots.
- Keep table image paths relative to the output Markdown or HTML file.
- Record converted and kept table counts in `report.json`.

Raw HTML:

- Allow simple raw HTML to pass through only when it is low risk.
- Warn on `<script>`, `<style>`, iframes, embedded widgets, class-dependent layouts, and unknown block-level HTML.
- Strip or escape unsafe constructs in platform Markdown variants.

## Platform Profiles

WeChat:

- Main output: `wechat.html`.
- Style: magazine-column.
- Best effort compatibility with WeChat rich text and future draft API content.
- Tables should normally be images.

Zhihu:

- Output: `platforms/zhihu.md`.
- Preserve headings, paragraphs, quotes, code fences, images, and links.
- Avoid complex inline HTML and section wrappers.
- Use table images by default.

Toutiao:

- Output: `platforms/toutiao.md`.
- Favor plain paragraphs, headings, lists, and images.
- Warn on long code blocks and complex tables.

Zsxq:

- Output: `platforms/zsxq.md`.
- Keep Markdown structure compatible with the existing `publish-zsxq-article` skill.
- Preserve image positions and avoid style-only HTML.

SMZDM:

- Output: `platforms/smzdm.md`.
- Preserve product-like links, image placement, lists, and clear paragraph structure.
- Warn on style-heavy blocks that may be stripped by the editor.

## Error Handling

Fail fast:

- Source Markdown does not exist.
- Output directory exists and `--overwrite` is not set.
- A local image reference cannot be resolved.
- Required output directories or files cannot be written.
- Table conversion is required but cannot run in `--strict` mode.

Warn and continue:

- Remote image links.
- Large images.
- Missing H1.
- Raw HTML with likely platform sanitization risk.
- Long code blocks.
- Tables kept as Markdown because table conversion is disabled.

`--strict` converts compatibility warnings into failures.

## Report Format

`report.json` should contain at least:

```json
{
  "source": "article.md",
  "title": "Article Title",
  "outputs": ["wechat.html", "preview.html", "platforms/zhihu.md"],
  "assets": [{"source": "media/a.png", "output": "assets/a.png"}],
  "tables": {"converted": 2, "kept": 0},
  "warnings": [{"code": "remote_image", "message": "Remote image was left unchanged"}],
  "next_steps": ["Open preview.html", "Review warnings before publishing"]
}
```

The exact JSON may include more fields, but these keys must remain stable because later publishing skills may consume them.

## Testing

Required verification after implementation:

```bash
python3 -m py_compile skills/format-platform-article/scripts/*.py
python3 -m unittest discover skills/format-platform-article/tests
python3 skills/format-platform-article/scripts/build_publish_package.py \
  skills/format-platform-article/tests/fixtures/article.md \
  --output /tmp/format-platform-article.publish \
  --overwrite
python3 -m json.tool skills/format-platform-article/evals/evals.json
```

Tests must cover:

- Title extraction and filename fallback.
- Image path resolution and asset copying.
- Missing local image failure.
- Output overwrite protection.
- WeChat HTML generation.
- Platform Markdown generation.
- Warning generation.
- End-to-end package creation.

## Implementation Notes

- Prefer Python for the first version because the repo's local skills already use Python helper scripts heavily.
- Keep dependencies minimal. If table rendering needs Pillow, call or reuse the existing `markdown-table-images` script path rather than duplicating the whole renderer.
- Do not modify `notion-to-md`; this skill consumes its output.
- Do not modify existing publishing skills in the first implementation unless a later plan explicitly scopes that integration.
- Keep the generated package portable by using relative paths.

## Acceptance Criteria

- A new `format-platform-article` skill exists under `skills/`.
- Running the CLI on the fixture article creates the expected publish package.
- `wechat.html` renders a magazine-column article with inline styling.
- All platform Markdown files are generated and non-empty.
- Local images are copied into `assets/` and referenced with relative paths.
- Table conversion behavior is represented in the output and report.
- `report.json` is valid JSON and includes outputs, assets, table counts, warnings, and next steps.
- Tests and smoke checks pass.
