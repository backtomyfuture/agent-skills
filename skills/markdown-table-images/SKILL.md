---
name: markdown-table-images
description: Convert large or publication-risky Markdown tables into polished PNG images and replace the original table blocks with local image links. Use this skill whenever the user needs to publish Markdown across platforms like Markdown Nice, WeChat Official Account, Zhihu, Xiaohongshu, Toutiao, Zsxq, or any editor where Markdown/HTML tables may break, especially when they mention table compatibility, rendering tables as images, table thresholds, prettier table screenshots, or multi-platform article publishing. Default to the publication-style rendering, not raw spreadsheet-like screenshots.
---

# Markdown Table Images

Use this skill to make Markdown articles safer for multi-platform publishing by turning large Markdown tables into polished local PNG images and replacing those table blocks with `![...](...)` image links.

This is useful because many article editors sanitize HTML, strip inline styles, or render wide tables poorly on mobile. A PNG keeps the table visually stable across Markdown Nice, WeChat, Zhihu, Xiaohongshu, Toutiao, Zsxq, and similar platforms.

## Default Style

Use the `publication` theme by default for real article publishing. This is the house style for this skill:

- Compact typography with `--font-size 24`.
- Dark table header for clear hierarchy.
- Soft grid lines instead of heavy spreadsheet borders.
- Alternating light row backgrounds.
- Center short columns such as time, difficulty, status, and counts.
- Add outer padding so the table image does not touch the article edge.
- Preserve emoji and symbol emoji using Apple Color Emoji fallback.

Use `--theme plain` only for debugging, neutral previews, or when the user explicitly asks for the old simple table look.

## Workflow

1. Identify the Markdown file or directory the user wants to process.
2. Choose thresholds:
   - Default: convert tables with at least `4` body rows, at least `3` columns, or at least `12` cells.
   - Default threshold mode is `any`: a table is converted when any threshold is met.
   - Use `--threshold-mode all` when the user wants only tables that meet every threshold.
   - Use stricter thresholds for platforms with weak table support, such as Toutiao or Xiaohongshu.
   - Use looser thresholds when the user only wants very large summary/comparison tables converted.
   - Keep `--theme publication` unless the user explicitly asks for a plain/debug table.
3. Run the bundled script:

```bash
uv run --with pillow python scripts/render_markdown_tables.py ARTICLE.md \
  --output ARTICLE.tables-as-images.md \
  --image-dir media/tables \
  --min-rows 4 \
  --min-cols 3 \
  --min-cells 12 \
  --threshold-mode any \
  --theme publication
```

4. Inspect the summary:
   - `converted`: number of tables replaced by images.
   - `kept`: number of tables left as Markdown.
   - `images`: generated PNG paths.
5. Verify the output Markdown contains local image links and the image files exist.

## Recommended Defaults

For cross-platform article publishing, use:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --output input.publish.md --image-dir media/tables
```

The default visual theme is `publication`: compact typography, a dark header, soft grid lines, centered short columns, and outer padding. Treat this as the normal output style for cross-platform publishing. Use `--theme plain` only when you want the older neutral/debug-style table rendering.

For Toutiao or Xiaohongshu, convert almost every table:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --output input.publish.md --image-dir media/tables --min-rows 1 --min-cols 2 --min-cells 2
```

For only large tables:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --output input.publish.md --image-dir media/tables --min-rows 6 --min-cols 4 --min-cells 24
```

For only tables that satisfy every threshold:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --output input.publish.md --image-dir media/tables --min-rows 6 --min-cols 4 --min-cells 24 --threshold-mode all
```

## Dependencies

The script requires Python 3.10+ and Pillow.

Prefer `uv` because it can provide Pillow without manually creating a virtual environment:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --output input.publish.md
```

If `uv` is not available, use a project or temporary virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pillow
```

On macOS, the script automatically tries Chinese-capable fonts such as Hiragino Sans GB and Arial Unicode. If CJK text renders incorrectly, pass an explicit font path:

```bash
uv run --with pillow python scripts/render_markdown_tables.py input.md --font "/System/Library/Fonts/Hiragino Sans GB.ttc"
```

The renderer also falls back to `/System/Library/Fonts/Apple Color Emoji.ttc` for emoji and symbol emoji such as `🗂️`, `📣`, `⭐`, and `⚠️`. This avoids missing-glyph boxes in table images. Complex ZWJ emoji may render as their component emoji depending on Pillow/macOS font support, but they should not render as square placeholder glyphs.

## Output Rules

- Keep image paths relative to the output Markdown file, so the article folder is portable.
- Put generated table images under the article's existing media folder when one exists.
- Use readable alt text like `表格 1` or the nearest preceding heading.
- Prefer `--theme publication` and avoid producing raw spreadsheet-like screenshots for publishable content.
- Do not delete the original input file unless the user explicitly asks for in-place replacement.
- If the user wants in-place replacement, create a backup first with `--backup`.

## Notes

- The script targets standard pipe tables (`| A | B |`) and does not attempt to parse raw HTML tables.
- Inline Markdown is simplified for image rendering: links keep their visible label, emphasis markers are removed, and `<br>` becomes a line break.
- Wide content is wrapped inside cells and rendered as a high-resolution PNG suitable for mobile article platforms.
- If the table image looks too large, lower `--font-size` to `22` or `20`. If it looks cramped, raise `--font-size` or use `--max-width 1600`.
- For summary tables like setup steps, pricing comparisons, tool matrices, or checklists, the publication theme is usually better than preserving the raw Markdown table aesthetic.
