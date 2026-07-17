# Markdown conventions for the email renderer

`render_email.py` parses a small, Notion-flavored Markdown dialect into styled
HTML blocks. It is NOT full CommonMark — it recognizes a specific set of block
patterns. Author your intermediate `.md` using exactly these patterns so the
output looks like the reference newsletter (the AI周报). Each pattern below maps
to one visual block; the "Gotcha" notes are real parser behaviors that will bite
you if ignored.

## Block reference

### Section header with PART pill — `# PART.NN 标题`
```
# PART.01 工作概述
```
Renders a solid-blue rounded **PART.01** pill with the title beside/under it.
This is the signature look. Use it for the 2–4 top-level sections of the report.
- Keep the label and title on ONE line (`# PART.01 工作概述`). If you put `# PART.01`
  alone, the parser merges the *next* block in as the subtitle — usually not what
  you want.
- Number them sequentially (PART.01, PART.02, …).

### Plain section header (no pill) — `# 标题`
```
# 本月小结
```
A `#` heading WITHOUT a `PART.NN` prefix renders as a heading with a blue
left-border bar. Use it for the concluding section (本期/本月小结) and the
内容摘要 is handled specially (see below).

### Group card — `### 标题` (the unified content container)
```
### 暑运安全
1. 梳理并下发2026年IT体系暑运工作单，完成WBS分解；
2. 组织互联网系统WAF、SSL、CDN加速自查，累计部署WAF防护域名==10个==；
3. 牵头完成互联网系统启用IP白名单。
```
A `###` heading plus everything under it (until the next heading/divider/table)
renders as ONE blue-left-border card: bold blue title, list/paragraph lines
inside. **This is the standard container for every leaf content group** — task
lists, project lists, status+narrative groups all use it, so the whole email
reads in a single visual grammar.
- Project/system lists: one numbered line per system with the name bolded at
  the start — `1. **CC系统**：代客下宠物功能已完成测试和上线；`
- A `**状态**：…` line can be the first line inside the card.
- A plain `#` section (e.g. 本月小结) auto-wraps its body lines into an
  untitled group card — don't add a `###` there.

### Sub-heading — `## 标题`
```
## 运维保障
```
`##` → plain medium blue sub-heading. Use it ONLY when a PART needs a second
grouping level above the `###` cards (e.g. PART 项目需求与运维保障 → `## 运维保障`
→ five `###` cards). If a PART has just one level of groups, go straight to `###`.

### Numbered / narrative lines
Consecutive non-blank lines become separate paragraphs (each its own `<p>`).
So a numbered list just works:
```
信息技术部本月重点工作包括：
1. 完成 A 功能开发并于 5 月 29 日上线；
2. 完成 B 接口切换；
3. 完成 C 策略配置。
```
Use numbered lists for multi-item work areas — they stay readable. Reserve cards
(below) for discrete named items.

### Accent highlight — `==关键数字==`
```
天航6月坐席助手使用率为==90.71%==，满足考核要求。
```
`==x==` renders in brand red + bold. Use it sparingly for the numbers/marks a
leader should spot at a glance: key figures in the 内容摘要 and summary-table
关键数据 column, 达标 marks (`==✅达标==`), the headline number in 状态 lines.
Don't paint whole sentences red — navy/blue stays dominant, red is an accent.

### Second-level items — `- ` dash lines
```
1. 完成官网系统改造：
- SSR项修改上线；
- 管理后台水印上线；
- SPNR日志记录写入优化。
```
A line starting with `- ` renders as an indented short-dash item (`– …`, 14px,
tighter spacing) under the preceding numbered line. Use it when the source has
real two-level numbering (`1. → （1）`) that would otherwise flatten into one
dense same-level list. If a group has more than 3-4 second-level items, prefer
promoting it to a `##`/`###` sub-heading instead.

### Status line — bold inline labels
```
**状态**：已完成　｜　**成效**：提质增效
```
`**x**` becomes bold inline. A line that is bold-only (`**信息安全**` with nothing
after) is treated as a sub-heading instead — so a status line MUST have text
after the closing `**` (the `：值` does that). Put a blank line after the status
line so it renders as its own paragraph.

### Callout cards (blue left border) — `——**名称**正文`
```
——**安全员浮动奖自动计算程序**根据出勤、等级等数据自动计算每月浮动奖，每月省 2-3 小时。
——**复训到期自动提醒程序**每月 1 日定时邮件提醒复训到期人员，每月省 1-2 小时。
```
Each `——**Name**body` line becomes a card: bold-blue title + description below,
with a blue left border.
- **Legacy/emphasis only.** The unified standard is the `###` group card with
  numbered bold-name lines (one card per group, not per item). Use per-item
  ——cards only if the user explicitly wants individual items showcased.
- **Gotcha — no colon after the name.** `——**Name**：body` leaves a stray `：` at
  the start of the body. Write `——**Name**body` (the title and body render on
  separate lines, so no separator is needed).
- Cards hold a single paragraph each. If an item needs a numbered sub-list, use a
  `##` sub-heading + list instead of a card.

### 内容摘要 (content summary) — must be the FIRST block
```
内容摘要
本月围绕……三大板块开展工作：完成 4 项需求交付，自研涉及 7 个系统（交付 4 个）……
本月核心主线为：**保障安全运行、深化自研提效、推进重点项目落地**。
```
If (and only if) the file's first block starts with the literal `内容摘要`, it
renders as a "内容摘要" heading followed by the summary paragraph(s). Keep the
summary lines directly under `内容摘要` with no blank line between them, then a
blank line before whatever follows (usually the summary table).

### Summary table — Notion `<table>` HTML
```
<table header-row="true">
<tr>
<td>板块</td>
<td>本月重点工作</td>
<td>关键数据</td>
</tr>
<tr>
<td>信息化建设</td>
<td>客座率提醒上线、金鹏积分调整、发票切换用友</td>
<td>4 项需求交付</td>
</tr>
</table>
```
Renders a blue-header, zebra-striped table; the first column is bold navy. Great
for an executive "板块 / 重点 / 关键数据" overview near the top.
- **Gotcha — one tag per line.** Each `<tr>`, `</tr>`, and `<td>…</td>` MUST be on
  its own line. The parser reads line-by-line: `<tr><td>a</td><td>b</td></tr>` all
  on one line will lose every cell. Column widths are auto-computed from content.
- `header-row="true"` makes the first row the styled header.

### Divider — `---`
```
---
```
A line that is exactly `---` renders a horizontal rule. Put one between PART
sections and before the conclusion. Surround it with blank lines.

### Insight callout (optional) — `**启发**`
```
**启发**
这里是分析/研判文字……
```
Renders a light-blue "💡 启发" callout box. Useful for a weekly/analytical report
(like the AI周报). For a factual work report, prefer omitting it rather than
inventing takeaways the source doesn't contain.

## Recommended document skeleton (monthly work report)
```
内容摘要
<one-paragraph overview>
本月核心主线为：**…**。

<summary table>

---

# PART.01 <板块一>
### <内容组一>
<numbered list>

### <内容组二>
<numbered list>

---

# PART.02 <项目板块>
### <项目组>
1. **系统一**：进展/成果；
2. **系统二**：进展/成果；

---

# PART.03 <合并板块>
### <内容组>
<numbered bold-name lines>

## <二级分组>（仅当板块内需要再分一层）
### <内容组>
<numbered list>

---

# PART.04 <研发板块>
### <重构/改造组>
**状态**：…　｜　**进展**：…

<narrative paragraph>

### <自研项目组>
1. **系统一**：进展；
2. **系统二**：进展；

---

# 本月小结
**总评**：<一句话总评>
**最大亮点**：<本月最大的一个亮点，含==关键数字==>
**下月关键**：<下月最重要的一件事>
```

Keep the 小结 to this three-line shape — a paragraph-style 小结 that re-lists
every板块 just repeats the 内容摘要 and leaders end up reading the same thing
twice.

## Other parser behaviors worth knowing
- **Trailing signature stripping.** Trailing paragraphs that start with `天津航空`,
  `信息技术部`, or a `YYYY年M月D日` date are auto-removed (the footer already shows
  org + date). Don't rely on a hand-written signature at the end — it'll vanish.
- **Header date.** If any paragraph contains a `YYYY年M月D日` string, the first such
  match becomes the header date; otherwise today's date is used.
- **Greeting** (`--greeting`) is injected above the whole newsletter, plain-text,
  one `<p>` per line — only in `--eml` mode.
