# Contracts

This file defines the structured artifacts used by `toutiao-content-pipeline`.

## `brief.json`

Use this shape after information collection and verification:

```json
{
  "run_topic": "AI Agent latest news",
  "generated_at": "2026-05-06T12:00:00+08:00",
  "time_range": "today",
  "items": [
    {
      "title": "Event title",
      "category": "tech",
      "heat_level": "phenomenon | high | notable",
      "freshness": "breaking | news | trend",
      "confidence": "multi_source_confirmed | primary_source_only | single_reliable_source | unverified",
      "source_quality": "primary | independent_media | industry_report | self_media | community_post | screenshot | unknown",
      "core_facts": [
        "Fact with source-backed wording"
      ],
      "key_numbers": [
        {"label": "funding", "value": "$10M", "source_url": "https://example.com"}
      ],
      "background": "Context needed to understand the event.",
      "reactions": [
        {"actor": "company", "claim": "What they said", "source_url": "https://example.com"}
      ],
      "source_urls": [
        "https://example.com/primary",
        "https://example.com/secondary"
      ],
      "source_notes": [
        "Primary source confirms release date; secondary source provides market context."
      ],
      "content_angles": [
        "practical analysis",
        "domestic vs overseas comparison"
      ],
      "visual_opportunities": [
        "cover card",
        "timeline card",
        "comparison table image"
      ],
      "target_platforms": ["toutiao_article", "weitoutiao"],
      "keywords": ["AI", "Agent", "automation"],
      "risk_notes": [
        "Single-company claim; avoid stating as market consensus."
      ],
      "publish_decision": "use | use_with_caveat | needs_user_choice | remove",
      "follow_up_questions": [
        "Need official pricing confirmation."
      ]
    }
  ]
}
```

## `payload.json`

The formatting script writes this shape:

```json
{
  "source_file": "/abs/path/draft.md",
  "mode": "article",
  "title": "Title for article editor",
  "title_file": "/tmp/.../title.txt",
  "body_file": "/tmp/.../body.txt",
  "body_chars": 3200,
  "images": [
    {
      "index": 1,
      "alt": "diagram",
      "src": "./images/diagram.png",
      "resolved_path": "/abs/path/images/diagram.png",
      "marker": "[[IMG_1]]",
      "exists": true
    }
  ],
  "warnings": []
}
```

Treat `payload.json` as the source of truth for browser staging.

## `visual_plan.json`

The visual helper writes this shape:

```json
{
  "source_file": "/abs/path/draft.md",
  "draft_with_visuals": "/abs/path/draft_with_visuals.md",
  "min_images": 3,
  "visuals": [
    {
      "id": "cover",
      "role": "cover",
      "html_file": "/abs/path/visuals/cover.html",
      "png_file": "/abs/path/visuals/cover.png",
      "open_url": "file:///abs/path/visuals/cover.html",
      "render_command": "agent-browser ..."
    }
  ],
  "warnings": []
}
```

Render PNGs before formatting. Use `draft_with_visuals.md` as the source file for `prepare_toutiao_payload.py`.

## Publish Log

Use `publish-log.md`:

```markdown
# Toutiao Publish Log

- Time:
- Mode:
- Title:
- Payload:
- Source count:
- Selected angle:
- Visual count:
- Review Gate:
- Browser URL:
- Status: staged_autosaved | saved_draft | final_published | blocked
- Final publish clicked: yes/no
- Draft button present: yes/no
- Images uploaded:
- Risk notes:
- Verification notes:
- User action needed:
```
