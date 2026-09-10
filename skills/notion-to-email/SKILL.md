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

Default for AI 周报 is the **approval draft** (呈阅给中心经理), not the later department-wide send.

## Workflow

1. **Get the Notion page URL** from the user's message.
2. **Fetch the page.** Prefer `ntn pages get <page-id>` (from the `notion-cli` skill). If that is unavailable, use the `notion-to-md` helper. Do not wait for a `notion_fetch` MCP tool — it is often not connected.
3. **Extract title** from the page's `Name` or `title` property. Use it as the email subject.
4. **Save only the body** to `/tmp/notion_email_input.md`. Strip YAML frontmatter / properties / ancestor paths. Write ONLY the page content.
5. **Use the fixed To / Cc — never look them up.** These are always the same for the AI 周报 approval draft; do **not** search Exchange sent mail for them:
   - To: `宗晓婷(Vicky) <xt_zong@tianjin-air.com>`
   - Cc: `张阳阳(Maggie) <yy-zhang1@tianjin-air.com>`
   - Do not send. Create an Exchange draft for the user to open and send.
6. **Run the render script** in `--eml` mode (always pass `--no-open` — the email goes straight to the Exchange drafts folder, so opening the `.eml` is unnecessary):

   ```bash
   python3 ~/.agents/skills/notion-to-email/scripts/render_email.py /tmp/notion_email_input.md \
     --title "<page title>" \
     --to "宗晓婷(Vicky) <xt_zong@tianjin-air.com>" \
     --cc "张阳阳(Maggie) <yy-zhang1@tianjin-air.com>" \
     --greeting "$(printf '%s\n' \
       '晓婷姐，下面为本周的AI周报最新版，呈阅。' \
       '建议后续审批路径：信息部总经理' \
       '' \
       '各位领导：' \
       '以下为<本周标签>全球及国内民航业数智化相关动态汇编，供参阅。')" \
     --eml --no-open
   ```

   Replace `<本周标签>` with the week in the title, e.g. `2026年9月第2周`. Keep the blank line before `各位领导：`. Do not put extra blank lines between the 呈阅 line and the 审批路径 line.
7. **Put it in the Exchange drafts folder.** Do not open the `.eml` — the draft in Outlook Drafts is the deliverable. `draft create` has no `--body-file` / `--attach`, so run:

   ```bash
   python3 ~/.agents/skills/notion-to-email/scripts/create_exchange_draft.py /tmp/notion-email-output.eml
   ```

   That script inlines CID images as data URIs and calls `exchange-cli draft create --body-type html`. Do **not** send. Do **not** pass `--confirm` to `draft send`.
8. **Tell the user**: "草稿已写入 Outlook 草稿箱，打开确认后点发送即可。" If Exchange draft creation fails, fall back to the `.eml` and say so.

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
| `--to` | Recipient. Pass `Name <email>`; the script encodes the display name only. |
| `--cc` | CC. Same format as `--to`. |
| `--greeting` | Plain text preface inserted **above** the newsletter card, Outlook-left-aligned. |
| `--output` | Output file path (default: `/tmp/notion-email-output.html`) |
| `--no-open` | Do not auto-open the result |

## Layout rules (match a real sent 周报)

The newsletter card is centered at 780px. Everything that is **not** the card must look like a normal Outlook compose body.

**Greeting / 呈阅 (above the card, left-aligned, full width):**

- Font: SimSun / 宋体, 16pt, `#212121`, line-height 24pt (do not use CSS `line-height:18pt` — Outlook then looks cramped).
- Do **not** wrap this block in a 780px centered table. That makes 呈阅 look like part of the card.
- After `各位领导：`, the next paragraph (`以下为…供参阅。`) has `text-indent:32pt` (two-character first-line indent).
- Keep one blank line before `各位领导：`. Do not add extra space between 呈阅 and 审批路径.
- Shrink the card's top padding when a greeting is present so `供参阅` does not sit far above the card.

**Contact line (below the card, still centered with it):**

- After the grey footer (`天津航空信息技术部` + date), close the bordered card.
- Then: `如有问题，请联系信息技术部傅强，谢谢。` — SimSun 16pt, `#212121`, centered, white background. Not inside the grey footer.

**To / Cc headers:**

- Pass `姓名(英文名) <email@domain>`.
- Never assign that whole string as a raw header. Encoding the angle brackets inside one encoded-word makes Outlook show mojibake. The script splits name vs address via `formataddr`.

Reference for spacing and Word HTML: a previously sent weekly `.eml` (e.g. `信息技术部 · AI周报 | 2026年8月第4周·…`). Prefer that file over screenshots when both exist.

## Important Details

- The page title is extracted from the Notion page properties (the `Name` field)
- When saving content to `/tmp/notion_email_input.md`, write ONLY the body — do NOT include properties, ancestor paths, or other metadata
- The render script handles parsing, template, logo embedding, smart table column widths, greeting layout, and To/Cc encoding
- Lines in the form `——"名称"后缀：说明` are auto-rendered as stacked newsletter cards instead of plain bullets
- Date is auto-detected from today's date by the script
- Logo (Tianjin Airlines) is bundled in `assets/logo.png`
  - **EML mode**: logo is embedded as MIME CID attachment
  - **HTML mode**: logo is embedded as base64 data URI — may not survive copy-paste to Outlook
- The output HTML uses Outlook-safe styling (no CSS gradients, inline styles, solid colors)

## Error Handling

- If the Notion fetch fails, tell the user to check the URL and that the page is shared with the Notion integration
- If `create_exchange_draft.py` fails, keep the `.eml` (do not open it) and tell the user where it is so they can import it manually
- If the render script fails, show the error output to the user

## Exchange draft (verified)

`exchange-cli draft create` **can** put this newsletter in Outlook Drafts. Verified 2026-09-10: HTML body, To/Cc, greeting, card, and contact line all survived; logo as a data URI rendered in Outlook.

Constraints:

- `draft create` has `--to`, `--cc`, `--subject`, `--body`, `--body-type text|html`. No `--body-file`, no `--attach`.
- Pass addresses only (`xt_zong@tianjin-air.com`), not `Name <email>` — Exchange resolves the display name.
- Always `--body-type html`. Rewrite `cid:logo` (and any other CID images) to `data:image/png;base64,...` before calling the CLI.
- Body is passed as `--body`; ARG_MAX on this Mac is 1MB, a typical 周报 (~55KB with logo) fits. If it ever fails with an argument-list error, say so — do not send.
- Creating a draft is a write, but it does not send. The user asked to put it in Drafts, so create it. Never `draft send` unless they explicitly ask to send.
