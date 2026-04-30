#!/usr/bin/env python3
"""
Prepare a Markdown article for Xiaohongshu publishing.

The script extracts a title, converts Markdown into plain note text, collects
topics from #topic# markers, resolves local images, and writes text files that
publishing backends can consume without shell quoting problems.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

NOTION_META_KEYS = {
    'Favorite', 'Archived', 'Type', 'Created', 'Created by',
    'Last edited time', 'Last edited by', 'Tags', 'Status',
    'Category', 'URL', 'Published', 'Date', 'Cover',
    'Updated', 'Project', 'Parent', 'Relation', 'Source',
}

IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)|!\[\[([^\]]+)\]\]')
LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
TOPIC_PATTERN = re.compile(r'(?<!\w)#([^#\n\r]{1,30})#')


def calc_xhs_title_units(s: str) -> int:
    """Calculate Xiaohongshu title units.

    This follows xiaohongshu-skills/scripts/title_utils.py:
    non-ASCII UTF-16 code units count as 2, ASCII code units count as 1,
    then the total is rounded up and divided by 2.
    """
    weighted = 0
    encoded = s.encode('utf-16-le')
    for i in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[i:i + 2], 'little')
        weighted += 2 if code_unit > 127 else 1
    return (weighted + 1) // 2


def truncate_xhs_title_units(s: str, max_units: int) -> str:
    if calc_xhs_title_units(s) <= max_units:
        return s
    while s and calc_xhs_title_units(s) > max_units:
        s = s[:-1]
    return s


def find_markdown_file(path: str) -> Path:
    p = Path(path)
    if p.is_file():
        return p
    if p.is_dir():
        md_files = sorted(p.glob('*.md'))
        if len(md_files) == 1:
            print(f'Auto-selected: {md_files[0].name}', file=sys.stderr)
            return md_files[0]
        if not md_files:
            raise SystemExit(f'Error: no .md files found in {path}')
        choices = '\n'.join(f'  {i}. {f.name}' for i, f in enumerate(md_files, 1))
        raise SystemExit(f'Multiple .md files found in {path}:\n{choices}\nSpecify the exact file path.')
    raise SystemExit(f'Error: path not found: {path}')


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith('---\n'):
        return {}, content
    end = content.find('\n---', 4)
    if end == -1:
        return {}, content
    block = content[4:end].strip()
    rest = content[end + 4:].lstrip('\n')
    meta: dict[str, object] = {}
    current_key = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith('  - ') and current_key:
            meta.setdefault(current_key, [])
            if isinstance(meta[current_key], list):
                meta[current_key].append(line[4:].strip().strip('"\''))
            continue
        if ':' in line:
            key, value = line.split(':', 1)
            current_key = key.strip()
            value = value.strip().strip('"\'')
            if value.startswith('[') and value.endswith(']'):
                items = [x.strip().strip('"\'') for x in value[1:-1].split(',') if x.strip()]
                meta[current_key] = items
            else:
                meta[current_key] = value
    return meta, rest


def strip_notion_metadata(lines: list[str]) -> list[str]:
    result: list[str] = []
    in_metadata = True
    for line in lines:
        if in_metadata:
            stripped = line.strip()
            if stripped and ':' in stripped:
                key = stripped.split(':', 1)[0].strip()
                if key in NOTION_META_KEYS:
                    continue
            if not stripped and not result:
                continue
            in_metadata = False
        result.append(line)
    return result


def extract_title(content: str, meta: dict, fallback: str) -> tuple[str, str]:
    title_value = meta.get('title') or meta.get('Title')
    if isinstance(title_value, str) and title_value.strip():
        return title_value.strip(), content

    lines = content.split('\n')
    for i, line in enumerate(lines[:8]):
        if line.startswith('# ') and not line.startswith('## '):
            title = line[2:].strip()
            body_lines = lines[:i] + lines[i + 1:]
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            return title, '\n'.join(body_lines)
    return fallback, content


def normalize_topic(topic: str) -> str:
    topic = topic.strip().strip('#').strip()
    topic = re.sub(r'\s+', '', topic)
    return topic[:30]


def collect_topics(content: str, meta: dict, cli_topics: list[str]) -> tuple[str, list[str]]:
    found: list[str] = []

    def replace(match: re.Match) -> str:
        topic = normalize_topic(match.group(1))
        if topic:
            found.append(topic)
        return ''

    cleaned = TOPIC_PATTERN.sub(replace, content)

    for key in ('tags', 'Tags', 'topics', 'Topics'):
        value = meta.get(key)
        if isinstance(value, list):
            found.extend(str(x) for x in value)
        elif isinstance(value, str) and value:
            found.extend(re.split(r'[,，、\s]+', value))

    found.extend(cli_topics)

    deduped: list[str] = []
    seen = set()
    for item in found:
        topic = normalize_topic(item)
        if topic and topic not in seen:
            seen.add(topic)
            deduped.append(topic)
    return cleaned, deduped


def resolve_image_path(src: str, source_dir: Path) -> str | None:
    if src.startswith('http://') or src.startswith('https://'):
        return None
    parsed = urlparse(src)
    raw_path = unquote(parsed.path if parsed.scheme == 'file' else src)
    candidates = []
    p = Path(raw_path)
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(source_dir / raw_path)
        candidates.append(source_dir / unquote(src))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def extract_images(content: str, source_dir: Path) -> tuple[str, list[dict], list[dict]]:
    images: list[dict] = []
    missing: list[dict] = []

    def replace(match: re.Match) -> str:
        alt = match.group(1) or ''
        src = match.group(2) or match.group(3) or ''
        idx = len(images) + len(missing) + 1
        resolved = resolve_image_path(src, source_dir)
        item = {
            'index': idx,
            'alt': alt,
            'src': src,
            'resolved_path': resolved,
        }
        if resolved:
            images.append(item)
        else:
            missing.append(item)
        return f'\n{alt}\n' if alt else '\n'

    return IMAGE_PATTERN.sub(replace, content), images, missing


def markdown_to_plain(content: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if re.search(r'^\s*\|.+\|\s*$', content, flags=re.MULTILINE):
        warnings.append('content contains Markdown tables; Xiaohongshu note text may need manual rewriting')
    if '```' in content:
        warnings.append('content contains fenced code blocks; code formatting will be flattened')

    text = content
    text = re.sub(r'^```[^\n]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s{0,3}>\s?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '- ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+[.)]\s+', lambda m: m.group(0).lstrip(), text, flags=re.MULTILINE)
    text = LINK_PATTERN.sub(lambda m: m.group(1), text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip(), warnings


def shorten_title(title: str, limit: int, no_truncate: bool) -> tuple[str, list[str]]:
    warnings: list[str] = []
    title = re.sub(r'\s+', ' ', title).strip()
    units = calc_xhs_title_units(title)
    if units <= limit or no_truncate:
        if units > limit:
            warnings.append(f'title is {units} Xiaohongshu units; expected <= {limit}')
        return title, warnings
    shortened = truncate_xhs_title_units(title, limit)
    warnings.append(
        f'title was shortened from {units} to {calc_xhs_title_units(shortened)} Xiaohongshu units'
    )
    return shortened, warnings


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Prepare Markdown for Xiaohongshu publishing')
    parser.add_argument('path', help='Markdown file or directory containing one .md file')
    parser.add_argument('--title', help='Override title')
    parser.add_argument('--topic', action='append', default=[], help='Topic/tag to add; may be repeated')
    parser.add_argument('--output-json', default='/tmp/xhs_note_payload.json')
    parser.add_argument('--title-file', default='/tmp/xhs_title.txt')
    parser.add_argument('--content-file', default='/tmp/xhs_content.txt')
    parser.add_argument('--title-limit', type=int, default=20)
    parser.add_argument('--note-limit', type=int, default=1000)
    parser.add_argument('--no-truncate-title', action='store_true')
    args = parser.parse_args()

    md_path = find_markdown_file(args.path)
    source_dir = md_path.parent
    raw = md_path.read_text(encoding='utf-8')

    meta, content = parse_frontmatter(raw)
    content = '\n'.join(strip_notion_metadata(content.split('\n')))
    original_title, body = extract_title(content, meta, md_path.stem)
    if args.title:
        original_title = args.title

    body, topics = collect_topics(body, meta, args.topic)
    body, images, missing_images = extract_images(body, source_dir)
    body, plain_warnings = markdown_to_plain(body)
    title, title_warnings = shorten_title(original_title, args.title_limit, args.no_truncate_title)

    warnings = plain_warnings + title_warnings
    if len(body) > args.note_limit:
        warnings.append(f'content is {len(body)} chars; use Xiaohongshu long article mode or shorten to <= {args.note_limit}')
    if missing_images:
        warnings.append(f'{len(missing_images)} image(s) could not be resolved to local files')

    title_file = Path(args.title_file)
    content_file = Path(args.content_file)
    output_json = Path(args.output_json)
    write_text(title_file, title)
    write_text(content_file, body)

    payload = {
        'title': title,
        'original_title': original_title,
        'mode': 'long_article' if len(body) > args.note_limit else 'note',
        'source_file': str(md_path.resolve()),
        'title_file': str(title_file.resolve()),
        'content_file': str(content_file.resolve()),
        'payload_file': str(output_json.resolve()),
        'content_chars': len(body),
        'title_chars': len(title),
        'title_units': calc_xhs_title_units(title),
        'original_title_units': calc_xhs_title_units(original_title),
        'topics': topics,
        'images': images,
        'missing_images': missing_images,
        'warnings': warnings,
    }
    write_text(output_json, json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
