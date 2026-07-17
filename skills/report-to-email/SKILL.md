---
name: report-to-email
description: >
  Convert a work report (PPTX / PDF / Word, or pasted text) into a polished,
  Tianjin Airlines-branded HTML email that matches the "AI周报" newsletter design
  — PART.NN section pills, a 内容摘要 summary table, blue-border cards, dividers,
  and a 本月小结 conclusion — and output an Outlook-ready .eml with the logo
  embedded. Use this skill whenever the user wants to turn a report or slide deck
  into an email or make a report "look nicer / 更美观 / 像周报那样", e.g.
  "把月报做成邮件", "这个 PPT 月报转成邮件格式", "把这份报告排成天航邮件",
  "月报转邮件", "report to email", "把工作汇报弄成 AI周报 那种格式发出去".
  Trigger even if they don't name the format — any "report/PPT/汇报 → email"
  request for an internal Tianjin Airlines report applies. NOT for converting a
  Notion page (use notion-to-email) or for editing/creating the slide deck itself
  (use pptx).
---

# Report → Tianjin Airlines Email

Turns an internal work report into a clean, scannable, Outlook-compatible HTML
email with Tianjin Airlines branding. The visual target is the company's
"信息技术部 · AI周报" newsletter: a navy header with logo, a 内容摘要 + overview
table, `PART.01/02/03` blue pills per section, dividers between sections,
blue-left-border cards for discrete items, and a concluding 小结.

The pipeline is always: **extract source text → rewrite as newsletter Markdown →
render → visually QA → emit .eml**. The renderer (`scripts/render_email.py`) does
all the styling; your job is to restructure the report's content into the
Markdown dialect it understands.

## Workflow

### 1. Get the source text
- **PPTX / DOCX**: `python3 scripts/extract_text.py <file>` (zip-based, reliable,
  prints text per slide / paragraph).
- **PDF**: use the `pdf` skill or the Read tool — they preserve layout far better
  than a regex dump. `extract_text.py` deliberately refuses PDFs.
- **Pasted text / .md**: use it directly.

Read the extracted text and understand the report's real structure (sections,
sub-areas, lists, any status/成效 labels, key numbers). Stay faithful to the
source — restructure and lightly condense, but do not invent facts, figures, or
analytical "takeaways" the report doesn't contain.

### 2. Write the newsletter Markdown
Save to a temp file, e.g. `/tmp/report_email_input.md`. Structure it using the
renderer's Markdown dialect — **read `references/markdown-conventions.md` for the
full pattern list, examples, and parser gotchas** (the table-cell-per-line rule
and the no-colon card rule in particular). The high-value blocks:

- `# PART.01 工作概述` → blue section pill with brand-red bar (the 2–5 main sections)
- `### 内容组` → THE unified container: one blue-left-border group card holding
  the title plus its list/paragraphs. Every leaf content group (task lists,
  project lists, status+narrative) goes in one; project items start with a bold
  system name (`1. **CC系统**：…`)
- `## 子标题` → plain blue sub-heading, only when a PART needs a grouping level
  above the `###` cards
- `---` → divider between sections
- `内容摘要` as the first block + a `<table header-row="true">` overview table
- `**状态**：…　｜　**成效**：…` → bold status line as the first card line
- `==关键数字==` → brand-red bold highlight for key figures / 达标 marks
- `# 本月小结` → red-bar heading; its 总评/最大亮点/下月关键 lines auto-wrap
  into an untitled group card

### 3. Render an HTML preview and QA it
```bash
python3 scripts/render_email.py /tmp/report_email_input.md \
  --title "信息技术部2026年5月工作月报" \
  --header-label "信息技术部 · 月报" \
  --output /tmp/report-email.html --no-open
python3 scripts/screenshot.py /tmp/report-email.html /tmp/report-email.png
```
Then **Read `/tmp/report-email.png` and inspect it critically** — confirm the logo
shows, the PART pills/table/cards/dividers all render, nothing overlaps or is
clipped, and the content is faithful. Fix the Markdown and re-render until it
looks right. (Using a subagent with fresh eyes for this pass is ideal but
optional.)

### 4. Generate the Outlook-ready .eml
```bash
python3 scripts/render_email.py /tmp/report_email_input.md \
  --title "信息技术部2026年5月工作月报" \
  --header-label "信息技术部 · 月报" \
  --greeting "各位领导、同事：
现将信息技术部 2026 年 5 月工作月报汇报如下，请查阅。" \
  --output /tmp/report-email.html --eml
```
This writes `/tmp/report-email.eml` (logo embedded as a CID attachment, so it
survives in Outlook) and opens it. Tell the user it's open in Outlook and to fill
in recipients before sending. Leave `--to/--cc` empty unless the user gave them.

## CLI options (`render_email.py`)

| Flag | Description |
|------|-------------|
| `--title` | The big header subtitle (and default email subject). Use a clean title like `信息技术部2026年5月工作月报`. |
| `--subject` | Email subject line when it should differ from the header title, e.g. `呈阅示：关于信息技术部2026年6月月报对外发布的请示`. Defaults to `--title`. |
| `--header-label` | Small caption above the subtitle. Default `信息技术部 · 月报`. Set per report type (e.g. `信息技术部 · 季报`). |
| `--eml` | Emit an Outlook-ready `.eml` (logo via CID). Use for the final deliverable. |
| `--greeting` | Plain-text greeting injected above the newsletter (eml mode). |
| `--to` / `--cc` | Recipients. Usually leave empty for a preview. |
| `--output` | Output path (`.eml` is derived from it in eml mode). |
| `--no-open` | Don't auto-open the result (use for the preview render). |

## Important details
- **Faithfulness over polish.** This is a real report going to leadership.
  Reorganize and summarize existing facts; never fabricate numbers or insights.
  When unsure whether something is in the source, leave it out.
- **Newest content only.** If the source contains a thread or stacked revisions,
  use the latest/topmost version.
- **What gets dropped.** Cover/closing decorative slide images are intentionally
  dropped (the point is a clean linear newsletter). If a content image is genuinely
  informative, ask the user whether to keep it — embedding extra inline images
  needs more than the bundled logo CID.
- **Branding is bundled.** `assets/logo.png` (Tianjin Airlines) is embedded
  automatically; the footer shows org + date. Navy stays the dominant color;
  brand red (`C_ACCENT`, sampled from the logo) is used only as accent — top/footer
  stripes, the vertical bar left of each PART pill, plain-`#` heading bars, and
  `==key figures==` highlights. Output is Outlook-safe (table layout, inline
  styles, solid colors — no gradients/external CSS; `color-scheme: light` metas
  for dark-mode clients; body text ≥14px with ≥1.7 line-height).
- **Width** is 780px (`EMAIL_WIDTH` in the renderer, user-confirmed preference;
  change only the constant if it must move). The fixed width is enforced with THREE redundant
  layers, because Outlook rewrites the HTML **when the user clicks send** (it
  strips `<style>`, classes, comments, and sometimes div styles — the draft looks
  fine at 780px but the sent mail stretches to 100% if any single layer is relied
  on): (1) a three-column wrapper table whose center `<td>` carries
  `width="780"` + `style="width:780px"` with fluid spacer `<td>`s on both sides
  (pure table attributes survive every sanitizer); (2) inline
  `style="width:780px;max-width:780px;margin:0 auto"` on the content table and a
  wrapping `<div>`; (3) an MSO "ghost table" (`<!--[if mso]>…<![endif]-->`) for
  Word-based renderers. Keep all three when editing the renderer, in both
  `render_html` and the greeting block in `generate_eml`.
- **Never emit `<hr>` (or any fixed-width element).** Word-based Outlook
  converts `<hr>` on send into an `<img>` whose width is frozen at the sender's
  compose-window width (seen in the wild: `width:19.5833in` ≈ 1880px). That
  unbreakable image blows out every ancestor table — including fixed-width ones —
  so the received mail stretches to full screen even though the 780px containers
  survive. Dividers are rendered as a 2px background-color `<td>` stripe instead
  (same pattern as the header/footer accent stripes). Apply the same rule to any
  new visual element: build it from `<td>` background/height, never `<hr>`/`<img>`.

## Error handling
- Render fails → show the error; most issues are malformed `<table>` blocks
  (cells not one-per-line) or a missing input file.
- Logo missing from the `.eml` → confirm `assets/logo.png` exists in the skill dir
  (the renderer resolves it relative to its own location).
