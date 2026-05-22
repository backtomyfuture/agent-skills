---
name: openrouter-paid-ai-index
description: Build a weekly Paid AI Inference Index from OpenRouter rankings and model pricing.
---

# OpenRouter Paid AI Index

Use this skill when the user wants to evaluate AI usage trends with OpenRouter
weekly rankings, paid-model token demand, free-model heat, and estimated paid
inference spend.

## Run

```bash
python3 skills/openrouter-paid-ai-index/scripts/openrouter_paid_ai_index.py \
  --output-json ./openrouter-paid-ai-index.json \
  --output-md ./openrouter-paid-ai-index.md
```

The script reads:

- `https://openrouter.ai/rankings?view=week` for weekly ranking usage.
- `https://openrouter.ai/api/v1/models` for model metadata and pricing.

## Outputs

- Paid Token Demand Index: prompt plus completion tokens for paid models.
- Free Usage Index: prompt plus completion tokens for free variants.
- Revenue Proxy: estimated USD cost using current model pricing.
- Constant Price Revenue: the same current usage priced with a base snapshot
  when `--base-json` is provided.

Use `--compare-json <previous-snapshot.json>` to print week-over-week changes.
Use `--base-json <base-snapshot.json>` to control for model price changes.
