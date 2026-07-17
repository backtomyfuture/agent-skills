# Maintenance Notes

Known technical debt, recorded for a future pass. Not urgent.

## Deduplicate shared publish helpers

`publish-mdnice-article`, `publish-zsxq-article`, and `publish-xiaohongshu-article`
each carry a near-identical copy of the same helper scripts:

- `scripts/notion_ingest.py` - mdnice and zsxq differ only in User-Agent;
  the xiaohongshu copy is the same logic with comments trimmed.
- `scripts/prepare_content.py` and `scripts/prepare_image.py` - mdnice and zsxq
  are near-duplicates (same function set, minor editor-specific branches).

Plan: extract a shared content-preparation module (single source of truth for
Notion ingest, title extraction, `[[IMG_N]]` markers, image localization) and
have the three skills import it. Requires updating script references in each
SKILL.md and re-running the three skills' tests.

## Related notes

- `format-platform-article` calls `markdown-table-images/scripts/render_markdown_tables.py`
  via a sibling relative path; both skills must stay installed side by side
  (a `table_converter_missing` warning fires if not).
- `format-platform-article` (xiaohongshu/zsxq plain-text renderers) and the
  standalone publish skills implement the same markdown-to-platform-text rules
  in parallel; keep output rules in sync when either side changes.
