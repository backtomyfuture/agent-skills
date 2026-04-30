---
name: notion-to-email
description: >
  Convert a Notion page into a professionally styled HTML email ready to paste into Outlook.
  Use this skill whenever the user asks to "turn a Notion page into an email", "convert Notion to email",
  "generate email from Notion", "notion to outlook", "notion 转邮件", "生成周报邮件",
  "把 Notion 页面转成邮件", or provides a Notion URL and mentions email/邮件/outlook/周报.
  Also trigger when the user says "notion-to-email" by name.
---

# Notion → Email Skill

Converts a Notion page into a polished, Outlook-compatible HTML email with Tianjin Airlines branding.

## Workflow

1. **Get the Notion page URL** from the user's message
2. **Fetch the page** using the `notion_fetch` MCP tool
3. **Extract title** from the page's `Name` or `title` property
4. **Save the raw content** to a temp file: `/tmp/notion_email_input.md`
5. **Run the render script** (preferred: `--eml` mode for best Outlook compatibility):
   ```bash
   python3 ~/.agents/skills/notion-to-email/scripts/render_email.py /tmp/notion_email_input.md \
     --title "<page title>" \
     --to "<recipient>" \
     --cc "<cc recipient>" \
     --greeting "<optional greeting text>" \
     --eml
   ```
6. **Tell the user**: "EML 邮件已生成并在 Outlook 中打开，确认后点发送即可。"

### Fallback: HTML preview mode (without `--eml`)

If the user only wants a browser preview (not direct Outlook import):
```bash
python3 ~/.agents/skills/notion-to-email/scripts/render_email.py /tmp/notion_email_input.md --title "<page title>"
```
This generates `/tmp/notion-email-output.html` and opens it in the browser. User can then Cmd+A → Cmd+C → paste into Outlook, but logo and table widths may not survive the paste.

## CLI Options

| Flag | Description |
|------|-------------|
| `--title` | Email subject line (default: "AI周报") |
| `--eml` | Generate `.eml` file instead of HTML. Recommended for Outlook. |
| `--to` | Recipient email address (To field) |
| `--cc` | CC email address |
| `--greeting` | Plain text greeting inserted above the newsletter body |
| `--output` | Output file path (default: `/tmp/notion-email-output.html`) |
| `--no-open` | Do not auto-open the result |

## Important Details

- The page title is extracted from the Notion page properties (the `Name` field)
- When saving content to `/tmp/notion_email_input.md`, write ONLY the `<content>` section from the fetch result — do NOT include properties, ancestor paths, or other metadata
- The render script handles everything: parsing, template, logo embedding, smart table column widths, and browser/Outlook opening
- Lines in the form `——"名称"后缀：说明` are auto-rendered as stacked newsletter cards instead of plain bullets, to improve scanability in Outlook
- Date is auto-detected from today's date by the script
- Logo (Tianjin Airlines) is bundled in `assets/logo.png`
  - **EML mode**: logo is embedded as MIME CID attachment — works perfectly in Outlook, no external URL needed
  - **HTML mode**: logo is embedded as base64 data URI — works in browser but may not survive copy-paste to Outlook
- The output HTML uses Outlook-safe styling (no CSS gradients, inline styles, solid colors)

## Error Handling

- If the Notion fetch fails, tell the user to check the URL and permissions
- If the render script fails, show the error output to the user
