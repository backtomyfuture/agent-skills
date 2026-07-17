#!/usr/bin/env python3
"""
Notion Markdown → Styled HTML Email Renderer
Converts Notion-flavored markdown content into an Outlook-compatible HTML email
with Tianjin Airlines branding.
"""

import argparse
import base64
import os
import re
import subprocess
import sys
from datetime import datetime
from html import escape

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
LOGO_PATH = os.path.join(SKILL_DIR, "assets", "logo.png")
OUTPUT_PATH = "/tmp/notion-email-output.html"

# ── Layout ─────────────────────────────────────────────────────
EMAIL_WIDTH = 780

# ── Color Palette ──────────────────────────────────────────────
C_HEADER_BG = "#1a3a6b"
C_PRIMARY = "#2563eb"
# Brand red sampled from assets/logo.png — accent only (bars, key figures),
# navy/blue stays the dominant color.
C_ACCENT = "#e01020"
C_HEADING = "#1a3a6b"
C_SUBHEADING = "#1e40af"
C_TEXT = "#333"
C_TABLE_HEADER = "#2563eb"
C_TABLE_STRIPE = "#f8fafc"
C_TABLE_BORDER = "#e5e9f0"
C_INSIGHT_BG = "#eff6ff"
C_FOOTER_BG = "#f0f3f8"
C_FOOTER_BORDER = "#e0e4ea"
C_ENTRY_CARD_BG = "#f8fafc"
C_ENTRY_CARD_BORDER = "#dbe3f0"


def load_logo_base64():
    if not os.path.exists(LOGO_PATH):
        return ""
    with open(LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def inline_markdown(text):
    """Convert inline markdown (bold, highlight, links) to HTML."""
    # Accent highlight: ==text== → brand-red bold (key figures, 达标 marks)
    text = re.sub(
        r'==(.+?)==',
        rf'<span style="color:{C_ACCENT};font-weight:700;">\1</span>',
        text,
    )
    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    # Already HTML tags pass through
    return text


def display_width(text):
    """Estimate display width: CJK chars and emoji count as 2, others as 1."""
    import unicodedata
    w = 0
    for ch in text:
        cat = unicodedata.category(ch)
        # Emoji render significantly wider than CJK in email clients (~20px vs ~14px)
        if cat.startswith('So'):
            w += 4
        elif unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def calc_column_widths(rows, col_count):
    """Calculate column widths proportionally based on content display width."""
    if col_count == 0:
        return []
    # Use max display width per column (not sum) for better proportion
    col_max_widths = [0] * col_count
    for row in rows:
        for i, cell in enumerate(row):
            if i < col_count:
                w = display_width(cell)
                col_max_widths[i] = max(col_max_widths[i], w)
    total = sum(col_max_widths) or 1
    widths = [max(30, int(100 * w / total)) for w in col_max_widths]
    # Normalize to 100%
    w_total = sum(widths)
    if w_total != 100:
        diff = 100 - w_total
        largest = widths.index(max(widths))
        widths[largest] += diff
    return widths


def parse_table_block(lines, start_idx):
    """
    Parse a Notion-style <table> block starting at start_idx.
    Returns (table_html, end_idx).
    """
    rows = []
    current_row = []
    i = start_idx
    has_header = False
    in_row = False

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("</table>"):
            if current_row:
                rows.append(current_row)
            i += 1
            break
        elif line.startswith("<table"):
            if 'header-row="true"' in line:
                has_header = True
            i += 1
            continue
        elif line.startswith("<tr"):
            in_row = True
            current_row = []
            i += 1
            continue
        elif line.startswith("</tr>"):
            if current_row:
                rows.append(current_row)
            current_row = []
            in_row = False
            i += 1
            continue
        elif line.startswith("<td"):
            # Extract cell content: <td>content</td> or <td ...>content</td>
            match = re.match(r'<td[^>]*>(.*?)</td>', line)
            if match:
                cell = match.group(1).strip()
            else:
                # Multi-part or no closing tag on same line
                cell = re.sub(r'^<td[^>]*>', '', line).strip()
            current_row.append(cell)
            i += 1
            continue
        else:
            i += 1
            continue

    if not rows:
        return "", i

    col_count = max(len(r) for r in rows)
    widths = calc_column_widths(rows, col_count)

    html_parts = []
    html_parts.append(
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;font-size:14px;line-height:1.7;margin-bottom:4px;table-layout:auto;">'
    )

    for row_idx, row in enumerate(rows):
        is_header = has_header and row_idx == 0
        data_idx = row_idx - (1 if has_header else 0)  # index among data rows
        if is_header:
            html_parts.append(f'  <tr style="background-color:{C_TABLE_HEADER};">')
        elif data_idx % 2 == 0:
            html_parts.append(f'  <tr style="background-color:{C_TABLE_STRIPE};">')
        else:
            html_parts.append('  <tr>')

        for col_idx, cell in enumerate(row):
            cell_html = inline_markdown(cell)
            width_attr = f' width="{widths[col_idx]}%"' if col_idx < len(widths) else ''
            border = f'border-bottom:1px solid {C_TABLE_BORDER};' if row_idx < len(rows) - 1 else ''

            if is_header:
                radius = ''
                nowrap = 'white-space:nowrap;' if col_idx == 0 else ''
                if col_idx == 0:
                    radius = 'border-radius:6px 0 0 0;'
                elif col_idx == len(row) - 1:
                    radius = 'border-radius:0 6px 0 0;'
                html_parts.append(
                    f'    <td style="padding:10px 14px;font-size:14px;line-height:1.7;color:#fff;font-weight:600;text-align:center;{nowrap}{radius}">'
                    f'{cell_html}</td>'
                )
            else:
                first_col_style = f'color:{C_HEADING};font-weight:600;white-space:nowrap;' if col_idx == 0 else f'color:{C_TEXT};'
                html_parts.append(
                    f'    <td style="padding:10px 14px;font-size:14px;line-height:1.7;text-align:center;{first_col_style}{border}">'
                    f'{cell_html}</td>'
                )

        html_parts.append('  </tr>')

    html_parts.append('</table>')
    return '\n'.join(html_parts), i


def parse_content(text):
    """
    Parse Notion markdown content into a list of blocks:
    Each block is a dict with 'type' and relevant data.
    Types: heading1, heading2, heading3, paragraph, table, divider, insight
    """
    lines = text.split('\n')
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Divider
        if stripped == '---':
            blocks.append({'type': 'divider'})
            i += 1
            continue

        # Table block
        if stripped.startswith('<table'):
            table_html, i = parse_table_block(lines, i)
            if table_html:
                blocks.append({'type': 'table', 'html': table_html})
            continue

        # Headings
        h_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if h_match:
            level = len(h_match.group(1))
            heading_text = h_match.group(2).strip()
            # Remove surrounding ** if present
            heading_text = re.sub(r'^\*\*(.+?)\*\*$', r'\1', heading_text)
            blocks.append({'type': f'heading{level}', 'text': heading_text})
            i += 1
            continue

        # Regular paragraph — collect consecutive non-special lines
        para_lines = []
        while i < len(lines):
            l = lines[i].strip()
            if not l or l == '---' or l.startswith('<table') or re.match(r'^#{1,3}\s+', l):
                break
            para_lines.append(l)
            i += 1

        if para_lines:
            para_text = '\n'.join(para_lines)

            # Check if this starts with "内容摘要" — split into summary heading + remaining content
            if not blocks and para_text.startswith('内容摘要'):
                blocks.append({'type': 'summary_heading'})
                remaining = para_text[len('内容摘要'):].strip()
                if remaining:
                    # Split remaining into lines; detect bold-only "核心主题" line
                    rem_lines = remaining.split('\n')
                    for rl in rem_lines:
                        rl_stripped = rl.strip()
                        if not rl_stripped:
                            continue
                        bold_match = re.match(r'^\*\*(.+?)\*\*$', rl_stripped)
                        if bold_match and '核心主题' in rl_stripped:
                            blocks.append({'type': 'core_theme', 'text': bold_match.group(1)})
                        else:
                            blocks.append({'type': 'paragraph', 'text': rl_stripped})
                continue

            # Check if this is an "insight" block: "**启发**" or "**启**发" followed by content
            normalized_para = para_text.strip().replace('**启**发', '**启发**')
            if normalized_para.startswith('**启发**') or para_text.strip() == '启发':
                # Extract insight content: everything after the marker on same or next lines
                insight_text = re.sub(r'^\*\*启\*?\*?发?\*?\*?\s*', '', para_text).strip()
                if insight_text:
                    blocks.append({'type': 'insight', 'text': insight_text})
                else:
                    blocks.append({'type': 'insight_header'})
            elif blocks and blocks[-1].get('type') == 'insight_header':
                blocks.pop()  # Remove the header marker
                blocks.append({'type': 'insight', 'text': para_text})
            else:
                # Split into sub-blocks: detect bold-only lines as sub-headings
                sub_blocks = []
                current_para = []
                j = 0
                while j < len(para_lines):
                    stripped_pl = para_lines[j].strip()
                    # Detect "**启**发" variant as insight header
                    if re.match(r'^\*\*启\*\*\s*发$', stripped_pl):
                        if current_para:
                            sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                            current_para = []
                        sub_blocks.append({'type': 'insight_header'})
                        j += 1
                        continue

                    # Detect bold-only line as sub-heading: **text** (entire line)
                    bold_match = re.match(r'^\*\*(.+?)\*\*$', stripped_pl)
                    if bold_match:
                        bold_text = bold_match.group(1)
                        # "启发" as bold-only line → insight header, not sub-heading
                        if bold_text == '启发':
                            if current_para:
                                sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                                current_para = []
                            sub_blocks.append({'type': 'insight_header'})
                        else:
                            if current_para:
                                sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                                current_para = []
                            sub_blocks.append({'type': 'heading2', 'text': bold_text})
                        j += 1
                        continue

                    if parse_named_dash_entry(stripped_pl):
                        if current_para:
                            sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                            current_para = []
                        named_lines = []
                        while j < len(para_lines):
                            candidate = para_lines[j].strip()
                            if not parse_named_dash_entry(candidate):
                                break
                            named_lines.append(candidate)
                            j += 1
                        sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(named_lines)})
                        continue

                    # Detect ——dash entries: split each as its own paragraph block
                    if re.match(r'^——', stripped_pl):
                        if current_para:
                            sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                            current_para = []
                        sub_blocks.append({'type': 'paragraph', 'text': stripped_pl})
                        j += 1
                        continue

                    current_para.append(stripped_pl)
                    j += 1
                if current_para:
                    sub_blocks.append({'type': 'paragraph', 'text': '\n'.join(current_para)})
                blocks.extend(sub_blocks)

    # Remove trailing signature lines (e.g., "天津航空信息技术部" and "2026年3月28日")
    while blocks and blocks[-1]['type'] == 'paragraph':
        text = blocks[-1]['text'].strip()
        if re.match(r'^(天津航空|信息技术部|\d{4}年\d{1,2}月\d{1,2}日)', text):
            blocks.pop()
        else:
            break
    # Remove trailing divider
    while blocks and blocks[-1]['type'] == 'divider':
        blocks.pop()

    # Post-process
    merged = []
    i = 0
    while i < len(blocks):
        # Merge standalone "启发" headers with the next paragraph
        if blocks[i]['type'] == 'insight_header' and i + 1 < len(blocks) and blocks[i + 1]['type'] == 'paragraph':
            merged.append({'type': 'insight', 'text': blocks[i + 1]['text']})
            i += 2
        # Merge PART heading with the next block as subtitle (paragraph or heading2)
        elif (blocks[i]['type'] in ('heading1', 'heading2')
              and detect_part_label(blocks[i]['text'])
              and detect_part_label(blocks[i]['text'])[1] == ''
              and i + 1 < len(blocks)
              and blocks[i + 1]['type'] in ('paragraph', 'heading2')):
            part_label = detect_part_label(blocks[i]['text'])[0]
            next_block = blocks[i + 1]
            if next_block['type'] == 'heading2':
                # Next block is a heading2 — use its text as subtitle directly
                merged.append({'type': blocks[i]['type'], 'text': f'{part_label}\n{next_block["text"]}'})
                i += 2
            else:
                # Next block is a paragraph — take first line as subtitle
                next_text = next_block['text']
                next_lines = next_text.split('\n')
                subtitle_line = next_lines[0].strip()
                merged.append({'type': blocks[i]['type'], 'text': f'{part_label}\n{subtitle_line}'})
                # Keep remaining lines as paragraph if any
                remaining = '\n'.join(next_lines[1:]).strip()
                if remaining:
                    merged.append({'type': 'paragraph', 'text': remaining})
                i += 2
        else:
            merged.append(blocks[i])
            i += 1

    # Unified group-card pass:
    # - "### 标题" + following paragraphs → one titled group card
    # - plain "# 标题" section (e.g. 本月小结) → heading + untitled group card
    carded = []
    i = 0
    while i < len(merged):
        b = merged[i]
        if b['type'] == 'heading3':
            paras = []
            j = i + 1
            while j < len(merged) and merged[j]['type'] == 'paragraph':
                paras.append(merged[j])
                j += 1
            carded.append({'type': 'group_card', 'title': b['text'], 'paras': paras})
            i = j
        elif b['type'] == 'heading1' and not detect_part_label(b['text']):
            carded.append(b)
            paras = []
            j = i + 1
            while j < len(merged) and merged[j]['type'] == 'paragraph':
                paras.append(merged[j])
                j += 1
            if paras:
                carded.append({'type': 'group_card', 'title': '', 'paras': paras})
            i = j
        else:
            carded.append(b)
            i += 1

    return carded


def detect_part_label(text):
    """Check if heading text contains a PART.XX label. Returns (label, remaining_text) or None."""
    # Handle merged format: "PART.01\nSubtitle text"
    first_line = text.split('\n')[0].strip()
    m = re.match(r'^(PART\.\d+)\s*(.*)', first_line, re.IGNORECASE)
    if m:
        remaining = m.group(2).strip()
        # If remaining is empty, check second line
        if not remaining and '\n' in text:
            remaining = text.split('\n', 1)[1].strip()
        return m.group(1).upper(), remaining
    return None


def parse_named_dash_entry(text):
    """Parse lines like ——“天机”预测模型：描述 into a title/body pair.
    Also handles general ——Title：Description patterns."""
    # Pattern 1: ——“名称”后缀：说明
    match = re.match(r'^——\s*["“](.+?)["”]\s*([^：:]*)[\uff1a:]\s*(.+)$', text)
    if match:
        name = match.group(1).strip()
        suffix = match.group(2).strip()
        description = match.group(3).strip()
        title = re.sub(r'\s+', ' ', f'{name}{suffix}').strip()
        if title and description:
            return {"title": title, "description": description}

    # Pattern 2: ——Title：Description (colon-separated, no quotes)
    # Title must be short (≤30 chars) to avoid matching colons deep inside narrative paragraphs
    match2 = re.match(r'^——\s*(.+?)[\uff1a:]\s*(.+)$', text)
    if match2:
        title = match2.group(1).strip()
        description = match2.group(2).strip()
        # Strip markdown bold markers for length check
        title_plain = re.sub(r'\*\*(.+?)\*\*', r'\1', title)
        if title and description and len(title_plain) <= 15:
            return {"title": title, "description": description}

    return None

def parse_dash_entry_name(raw_line):
    """Extract bold entity name and body from a ——**Name**body line.
    Returns (name_html, body_html) or None if no bold name found."""
    stripped = raw_line.strip()
    # Pattern A: ——**Name**body  (bold at the start after ——)
    m = re.match(r'^——\s*\*\*(.+?)\*\*(.*)$', stripped)
    if m:
        name = m.group(1).strip()
        body = m.group(2).lstrip('，、,').strip()
        return name, body
    # Pattern B: ——prefix**Name**body  (bold appears after some prefix text)
    m = re.match(r'^——\s*(.+?)\*\*(.+?)\*\*(.*)$', stripped)
    if m:
        prefix = m.group(1).strip()
        bold_part = m.group(2).strip()
        suffix = m.group(3).lstrip('，、,').strip()
        name = f'{prefix}<strong>{bold_part}</strong>'
        return name, suffix
    return None


def render_part_pill(label, subtitle_html):
    """Blue PART pill with a brand-red vertical bar on its left."""
    return (
        f'<tr><td style="padding:20px 48px 0;">\n'
        f'  <table cellpadding="0" cellspacing="0"><tr>\n'
        f'    <td width="5" style="background-color:{C_ACCENT};font-size:0;line-height:0;">&nbsp;</td>\n'
        f'    <td width="10" style="font-size:0;line-height:0;">&nbsp;</td>\n'
        f'    <td style="background-color:{C_PRIMARY};color:#fff;font-size:20px;font-weight:700;'
        f'padding:5px 14px;letter-spacing:1px;border-radius:3px;">{label}</td>\n'
        f'  </tr></table>\n'
        f'  <h2 style="margin:8px 0 10px;font-size:20px;color:{C_HEADING};">{subtitle_html}</h2>\n'
        f'</td></tr>'
    )


def render_group_card(title, paras):
    """One blue-left-border card holding a whole content group: optional bold
    blue title plus every line of the collected paragraphs (the unified 图1
    style — task lists, project lists, and 小结 all share this container)."""
    parts = []
    if title:
        parts.append(
            f'<p style="margin:0 0 10px;font-size:15px;font-weight:700;'
            f'color:{C_PRIMARY};">{inline_markdown(title)}</p>'
        )
    for para in paras:
        for raw_l in para['text'].split('\n'):
            l = raw_l.strip()
            if not l:
                continue
            m = re.match(r'^-\s+(.*)$', l)
            if m:
                parts.append(
                    f'<p style="margin:0 0 8px 16px;font-size:14px;color:{C_TEXT};'
                    f'line-height:1.7;">– {inline_markdown(m.group(1))}</p>'
                )
            else:
                parts.append(
                    f'<p style="margin:0 0 10px;font-size:14px;color:{C_TEXT};'
                    f'line-height:1.75;">{inline_markdown(l)}</p>'
                )
    return (
        f'<tr><td style="padding:0 48px 14px;">\n'
        f'<table width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="border-left:4px solid {C_PRIMARY};'
        f'background-color:{C_ENTRY_CARD_BG};padding:14px 18px 6px;">\n'
        f'{"".join(parts)}'
        f'</td></tr></table>\n'
        f'</td></tr>'
    )


def render_block(block):
    """Render a single block to HTML."""
    btype = block['type']

    if btype == 'group_card':
        return render_group_card(block['title'], block['paras'])

    if btype == 'summary_heading':
        return (
            f'<tr><td style="padding:20px 48px 8px;">'
            f'<h2 style="margin:0;font-size:20px;font-weight:700;color:{C_HEADING};">内容摘要</h2>'
            f'</td></tr>'
        )

    if btype == 'core_theme':
        text = escape(block['text'])
        return (
            f'<tr><td style="padding:0 48px 12px;">'
            f'<p style="margin:0;font-size:15px;font-weight:700;color:{C_PRIMARY};line-height:1.85;">{text}</p>'
            f'</td></tr>'
        )

    if btype == 'divider':
        # Never emit <hr>: Word-based Outlook converts it on send into an <img>
        # whose width is frozen at the compose-window width (e.g. 19.58in),
        # blowing every ancestor table out to full screen. A background-color
        # td (same pattern as the accent stripes) survives the rewrite.
        return (
            '<tr><td style="padding:4px 48px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;">'
            '<tr><td style="background-color:#eef1f6;height:2px;font-size:0;line-height:0;">&nbsp;</td></tr>'
            '</table>'
            '</td></tr>'
        )

    if btype == 'table':
        return f'<tr><td style="padding:0 48px 8px;">\n{block["html"]}\n</td></tr>'

    if btype == 'heading1':
        text = inline_markdown(block['text'])
        part = detect_part_label(block['text'])
        if part:
            label, subtitle = part
            return render_part_pill(label, inline_markdown(subtitle))
        # Regular H1 — use as section heading with brand-red left border
        return (
            f'<tr><td style="padding:20px 48px 0;">\n'
            f'  <h2 style="margin:0 0 12px;font-size:20px;color:{C_HEADING};'
            f'border-left:5px solid {C_ACCENT};padding-left:14px;">{text}</h2>\n'
            f'</td></tr>'
        )

    if btype == 'heading2':
        text = inline_markdown(block['text'])
        part = detect_part_label(block['text'])
        if part:
            label, subtitle = part
            return render_part_pill(label, inline_markdown(subtitle))
        return (
            f'<tr><td style="padding:16px 48px 0;">\n'
            f'  <h3 style="margin:0 0 8px;font-size:16px;color:{C_SUBHEADING};">{text}</h3>\n'
            f'</td></tr>'
        )

    if btype == 'heading3':
        text = inline_markdown(block['text'])
        return (
            f'<tr><td style="padding:12px 48px 0;">\n'
            f'  <h4 style="margin:0 0 6px;font-size:15px;color:{C_SUBHEADING};">{text}</h4>\n'
            f'</td></tr>'
        )

    if btype == 'paragraph':
        raw_text = block['text']
        text = inline_markdown(raw_text)
        raw_lines = raw_text.split('\n')
        lines = text.split('\n')
        non_empty = [l for l in lines if l.strip()]
        raw_non_empty = [l for l in raw_lines if l.strip()]

        # Use raw (pre-inline-markdown) text for named-entry detection
        # to avoid false matches on colons inside the paragraph body
        named_entries = [parse_named_dash_entry(l.strip()) for l in raw_non_empty]
        if named_entries and all(named_entries):
            cards = ''.join(
                f'<tr><td style="padding:0 0 10px;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" '
                f'style="border-collapse:separate;background-color:{C_ENTRY_CARD_BG};'
                f'border:1px solid {C_ENTRY_CARD_BORDER};">'
                f'<tr><td style="padding:14px 18px;">'
                f'<p style="margin:0 0 6px;font-size:15px;font-weight:700;color:{C_HEADING};">'
                f'{inline_markdown(entry["title"])}</p>'
                f'<p style="margin:0;font-size:14px;color:{C_TEXT};line-height:1.75;">'
                f'{inline_markdown(entry["description"])}</p>'
                f'</td></tr></table>'
                f'</td></tr>\n'
                for entry in named_entries
            )
            return (
                f'<tr><td style="padding:0 48px 12px;">\n'
                f'<table width="100%" cellpadding="0" cellspacing="0">\n{cards}</table>\n'
                f'</td></tr>'
            )

        # Detect if all lines are dash-prefixed list items (——)
        dash_lines = [l for l in raw_non_empty if re.match(r'^——', l.strip())]
        if dash_lines and len(dash_lines) == len(raw_non_empty):
            # Try callout-card style: extract bold entity name as mini-heading
            cards = []
            for raw_l in raw_non_empty:
                parsed = parse_dash_entry_name(raw_l)
                if parsed:
                    name, body = parsed
                    name_html = inline_markdown(name)
                    body_html = inline_markdown(body)
                    cards.append(
                        f'<tr><td style="padding:0 0 10px;">'
                        f'<table width="100%" cellpadding="0" cellspacing="0">'
                        f'<tr><td style="border-left:4px solid {C_PRIMARY};padding:12px 18px;'
                        f'background-color:{C_ENTRY_CARD_BG};">'
                        f'<p style="margin:0 0 6px;font-size:15px;font-weight:700;color:{C_PRIMARY};">'
                        f'{name_html}</p>'
                        f'<p style="margin:0;font-size:14px;color:{C_TEXT};line-height:1.75;">'
                        f'{body_html}</p>'
                        f'</td></tr></table>'
                        f'</td></tr>\n'
                    )
                else:
                    # No bold name — simple bullet style
                    inlined = inline_markdown(re.sub(r'^——\s*', '', raw_l.strip()))
                    cards.append(
                        f'<tr><td style="padding:0 0 10px;">'
                        f'<table width="100%" cellpadding="0" cellspacing="0">'
                        f'<tr><td style="border-left:4px solid {C_PRIMARY};padding:12px 18px;'
                        f'background-color:{C_ENTRY_CARD_BG};">'
                        f'<p style="margin:0;font-size:14px;color:{C_TEXT};line-height:1.75;">'
                        f'{inlined}</p>'
                        f'</td></tr></table>'
                        f'</td></tr>\n'
                    )
            return (
                f'<tr><td style="padding:0 48px 12px;">\n'
                f'<table width="100%" cellpadding="0" cellspacing="0">\n{"".join(cards)}</table>\n'
                f'</td></tr>'
            )

        def para_line(l):
            # "- xxx" → indented second-level item (short dash), lighter rhythm
            # than the numbered first-level lines
            m = re.match(r'^-\s+(.*)$', l)
            if m:
                return (
                    f'<p style="margin:0 0 8px 18px;font-size:14px;color:{C_TEXT};'
                    f'line-height:1.7;">– {m.group(1)}</p>\n'
                )
            return f'<p style="margin:0 0 16px;font-size:15px;color:{C_TEXT};line-height:1.85;">{l}</p>\n'

        paras = ''.join(para_line(l) for l in non_empty)
        return f'<tr><td style="padding:0 48px;">\n{paras}</td></tr>'

    if btype == 'insight':
        text = inline_markdown(block['text'])
        lines = text.split('\n')
        content = ''.join(
            f'<p style="margin:0 0 6px;font-size:14px;color:{C_TEXT};line-height:1.75;">{l}</p>\n'
            for l in lines if l.strip()
        )
        return (
            f'<tr><td style="padding:4px 48px 20px;">\n'
            f'  <table width="100%" cellpadding="0" cellspacing="0">\n'
            f'    <tr>\n'
            f'      <td style="background-color:{C_INSIGHT_BG};border-left:5px solid {C_PRIMARY};'
            f'border-radius:0 6px 6px 0;padding:14px 18px;">\n'
            f'        <p style="margin:0 0 4px;font-size:14px;font-weight:700;color:{C_PRIMARY};">💡 启发</p>\n'
            f'        {content}\n'
            f'      </td>\n'
            f'    </tr>\n'
            f'  </table>\n'
            f'</td></tr>'
        )

    return ''


def render_html(title, blocks, logo_b64, date_str, logo_mode='base64',
                header_label="信息技术部 · 月报"):
    """Assemble the full HTML email.
    logo_mode: 'base64' for browser preview, 'cid' for EML embedding.
    header_label: the small caption line above the big subtitle in the header.
    """
    # Render all blocks
    body_html = '\n\n'.join(render_block(b) for b in blocks if render_block(b))

    # Small caption shown above the big subtitle (e.g. "信息技术部 · 月报").
    header_title = header_label

    # Extract week label and subtitle from title
    # Format: "信息技术部 · AI周报 | 2026年3月第四周·民航业数智化动态与我司战略启示"
    subtitle = title
    week_label = ""
    if '|' in title:
        subtitle = title.split('|', 1)[1].strip()
        if '·' in subtitle:
            sub_parts = subtitle.split('·', 1)
            week_label = sub_parts[0].strip()
            subtitle = sub_parts[1].strip()

    # Date is always today (passed via date_str); do NOT extract from content
    # paragraphs — body text often contains unrelated dates (e.g. deadlines)
    # that would override the report date.

    # Use week_label in header if available
    header_date = week_label if week_label else date_str

    logo_img = ''
    spacer = ''
    if logo_mode == 'cid':
        logo_img = (
            f'<td align="left" valign="middle" width="140">'
            f'<img src="cid:logo" alt="天津航空" '
            f'width="134" height="50" style="height:50px;width:134px;display:block;">'
            f'</td>'
        )
        spacer = '<td width="140"></td>'
    elif logo_b64:
        logo_img = (
            f'<td align="left" valign="middle" width="140">'
            f'<img src="data:image/png;base64,{logo_b64}" alt="天津航空" '
            f'width="134" height="50" style="height:50px;width:134px;display:block;">'
            f'</td>'
        )
        spacer = '<td width="140"></td>'

    # Outlook-safe solid colors on the navy header; both pass 4.5:1 contrast
    # so the banner stays readable even if a client force-inverts colors
    header_subtitle_color = "#d5deee"
    header_date_color = "#a6b8d6"

    html = f'''<!DOCTYPE html>
<html lang="zh-CN" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<!--[if gte mso 9]>
<xml>
<o:OfficeDocumentSettings>
<o:AllowPNG/>
<o:PixelsPerInch>96</o:PixelsPerInch>
</o:OfficeDocumentSettings>
</xml>
<![endif]-->
<title>{escape(title)}</title>
<style type="text/css">
  body, table, td {{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
  table, td {{mso-table-lspace:0pt;mso-table-rspace:0pt;}}
  .email-container {{width:{EMAIL_WIDTH}px !important;max-width:{EMAIL_WIDTH}px !important;min-width:{EMAIL_WIDTH}px !important;Margin:0 auto !important;margin:0 auto !important;}}
</style>
</head>
<body style="margin:0;padding:0;background-color:#ffffff;font-family:'Helvetica Neue',Arial,'PingFang SC','Microsoft YaHei',sans-serif;text-align:center;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background-color:#ffffff;text-align:center;">
<tr>
<td style="font-size:1px;line-height:1px;">&nbsp;</td>
<td align="center" valign="top" width="{EMAIL_WIDTH}" style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;padding:24px 0;text-align:center;">

<!--[if mso]>
<table role="presentation" width="{EMAIL_WIDTH}" cellpadding="0" cellspacing="0" style="width:{EMAIL_WIDTH}px;" align="center"><tr><td align="center">
<![endif]-->
<div style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;min-width:{EMAIL_WIDTH}px;Margin:0 auto;margin:0 auto;">
<table role="presentation" class="email-container" width="{EMAIL_WIDTH}" cellpadding="0" cellspacing="0" align="center" style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;min-width:{EMAIL_WIDTH}px;Margin:0 auto;margin:0 auto;background-color:#ffffff;border:1px solid #e0e4ea;text-align:left;">

<!-- Top Accent Stripe (brand red) -->
<tr><td style="background-color:{C_ACCENT};height:4px;font-size:0;line-height:0;">&nbsp;</td></tr>

<!-- Header -->
<tr>
<td style="background-color:{C_HEADER_BG};padding:28px 48px;">
  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    {logo_img}
    <td align="center" valign="middle">
      <p style="margin:0 0 4px;font-size:14px;color:{header_subtitle_color};letter-spacing:2px;">{escape(header_title)}</p>
      <h1 style="margin:0;font-size:24px;font-weight:700;color:#ffffff;line-height:1.5;">{escape(subtitle)}</h1>
      <p style="margin:8px 0 0;font-size:13px;color:{header_date_color};">{header_date}</p>
    </td>
    {spacer}
  </tr></table>
</td>
</tr>

{body_html}

<!-- Footer -->
<tr>
<td style="padding:0;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="background-color:{C_ACCENT};height:3px;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="background-color:{C_FOOTER_BG};padding:24px 48px;text-align:center;">
      <p style="margin:0 0 4px;font-size:13px;color:#555;font-weight:600;">天津航空信息技术部</p>
      <p style="margin:0;font-size:12px;color:#999;">{date_str}</p>
    </td></tr>
  </table>
</td>
</tr>

</table>
</div>
<!--[if mso]>
</td></tr></table>
<![endif]-->
</td>
<td style="font-size:1px;line-height:1px;">&nbsp;</td>
</tr>
</table>
</body>
</html>'''

    return html


def generate_eml(html_body, title, logo_path, output_path,
                 mail_to='', mail_cc='', greeting=''):
    """Generate a .eml file with HTML body and CID-embedded logo."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.utils import formatdate

    # Inject greeting above the newsletter if provided
    if greeting:
        greeting_lines = greeting.strip().split('\n')

        def _greeting_line_html(line):
            if not line.strip():
                return '<p style="margin:0 0 8px;">&nbsp;</p>\n'
            # Preserve leading whitespace by converting to &nbsp;
            stripped = line.lstrip(' \t')
            leading = len(line) - len(stripped)
            prefix = '&nbsp;' * leading if leading else ''
            return (
                f'<p style="margin:0 0 8px;font-size:15px;color:#333;'
                f'line-height:1.85;">'
                f'{prefix}{escape(stripped)}</p>\n'
            )

        greeting_html = ''.join(_greeting_line_html(l) for l in greeting_lines)
        greeting_block = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="width:100%;background-color:#ffffff;text-align:center;">\n'
            f'<tr>\n'
            f'<td style="font-size:1px;line-height:1px;">&nbsp;</td>\n'
            f'<td align="center" valign="top" width="{EMAIL_WIDTH}" style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;padding:12px 0 0;text-align:center;">\n'
            f'<!--[if mso]>\n'
            f'<table role="presentation" width="{EMAIL_WIDTH}" cellpadding="0" cellspacing="0" style="width:{EMAIL_WIDTH}px;" align="center"><tr><td align="center">\n'
            f'<![endif]-->\n'
            f'<div style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;min-width:{EMAIL_WIDTH}px;Margin:0 auto;margin:0 auto;">\n'
            f'<table role="presentation" class="email-container" width="{EMAIL_WIDTH}" cellpadding="0" cellspacing="0" align="center" '
            f'style="width:{EMAIL_WIDTH}px;max-width:{EMAIL_WIDTH}px;min-width:{EMAIL_WIDTH}px;Margin:0 auto;margin:0 auto;">\n'
            f'<tr><td style="padding:0 4px;">\n'
            f'{greeting_html}'
            f'</td></tr></table>\n'
            f'</div>\n'
            f'<!--[if mso]>\n'
            f'</td></tr></table>\n'
            f'<![endif]-->\n'
            f'</td>\n'
            f'<td style="font-size:1px;line-height:1px;">&nbsp;</td>\n'
            f'</tr></table>\n'
        )
        html_body = html_body.replace(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background-color:#ffffff;text-align:center;">',
            greeting_block + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background-color:#ffffff;text-align:center;">',
            1
        )

    msg = MIMEMultipart('related')
    msg['Subject'] = title
    msg['From'] = ''
    msg['To'] = mail_to
    if mail_cc:
        msg['Cc'] = mail_cc
    msg['Date'] = formatdate(localtime=True)
    msg['MIME-Version'] = '1.0'

    # HTML body
    html_part = MIMEText(html_body, 'html', 'utf-8')
    msg.attach(html_part)

    # Logo as CID attachment
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo_data = f.read()
        img_part = MIMEImage(logo_data, _subtype='png')
        img_part.add_header('Content-ID', '<logo>')
        img_part.add_header('Content-Disposition', 'inline', filename='logo.png')
        msg.attach(img_part)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(msg.as_string())

    return output_path


def main():
    parser = argparse.ArgumentParser(description='Render Notion content as styled HTML email')
    parser.add_argument('input_file', help='Path to the Notion markdown content file')
    parser.add_argument('--title', default='AI周报', help='Email title')
    parser.add_argument('--subject', default='',
                        help='Email subject line (eml mode); defaults to --title. '
                             'Use when the subject should differ from the header title, '
                             'e.g. "呈阅示：关于信息技术部2026年6月月报对外发布的请示"')
    parser.add_argument('--output', default=OUTPUT_PATH, help='Output HTML file path')
    parser.add_argument('--eml', action='store_true', help='Generate .eml file for Outlook')
    parser.add_argument('--to', default='', help='Recipient email address')
    parser.add_argument('--cc', default='', help='CC email address')
    parser.add_argument('--greeting', default='', help='Greeting text above the newsletter')
    parser.add_argument('--header-label', default='信息技术部 · 月报',
                        help='Small caption above the big subtitle in the header '
                             '(e.g. "信息技术部 · 月报")')
    parser.add_argument('--no-open', action='store_true', help='Do not auto-open in browser')
    args = parser.parse_args()

    # Read input
    with open(args.input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Load logo
    logo_b64 = load_logo_base64()

    # Date
    date_str = datetime.now().strftime('%Y年%-m月%-d日')

    # Parse and render
    blocks = parse_content(content)

    if args.eml:
        # Generate EML with CID logo
        html = render_html(args.title, blocks, logo_b64, date_str, logo_mode='cid',
                           header_label=args.header_label)
        eml_path = args.output.rsplit('.', 1)[0] + '.eml'
        generate_eml(html, args.subject or args.title, LOGO_PATH, eml_path,
                     mail_to=args.to, mail_cc=args.cc, greeting=args.greeting)
        print(f"✅ EML email generated: {eml_path}")

        if not args.no_open:
            if sys.platform == 'darwin':
                subprocess.run(['open', eml_path])
            elif sys.platform == 'linux':
                subprocess.run(['xdg-open', eml_path])
            else:
                subprocess.run(['start', eml_path], shell=True)
    else:
        # Generate HTML for browser preview
        html = render_html(args.title, blocks, logo_b64, date_str,
                           header_label=args.header_label)

        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"✅ HTML email generated: {args.output}")

        if not args.no_open:
            if sys.platform == 'darwin':
                subprocess.run(['open', args.output])
            elif sys.platform == 'linux':
                subprocess.run(['xdg-open', args.output])
            else:
                subprocess.run(['start', args.output], shell=True)


if __name__ == '__main__':
    main()
