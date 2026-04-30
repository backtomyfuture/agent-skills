#!/usr/bin/env python3
"""
Prepare Markdown content for Markdown Nice editor injection.

Reads a Markdown file, strips Notion/export metadata, extracts title,
and writes a self-contained JS file that can be eval'd by agent-browser
to paste the content into the Markdown Nice editor.

Usage:
    python3 prepare_content.py /path/to/article.md
    python3 prepare_content.py /path/to/article.md --output /tmp/mdnice_paste_content.js
    python3 prepare_content.py /path/to/article.md --title "Custom Title"

Then run:
    agent-browser --session-name mdnice eval "$(cat /tmp/mdnice_paste_content.js)"

Output JSON from eval: { success, charCount, method }
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# Notion export metadata lines to strip (key: value pattern at file start)
NOTION_META_KEYS = {
    'Favorite', 'Archived', 'Type', 'Created', 'Created by',
    'Last edited time', 'Last edited by', 'Tags', 'Status',
    'Category', 'URL', 'Published', 'Date', 'Cover',
    'Updated', 'Project', 'Parent', 'Relation', 'Source',
}

# Image reference patterns to strip (images handled separately)
IMAGE_PATTERNS = [
    r'!\[([^\]]*)\]\([^)]+\)',          # ![alt](url)
    r'!\[\[([^\]]+)\]\]',               # ![[wikilink]]
]


def find_markdown_file(path: str) -> str:
    """If path is a directory, find the single .md file or list choices."""
    p = Path(path)
    if p.is_file():
        return str(p)

    if p.is_dir():
        md_files = sorted(p.glob('*.md'))
        if len(md_files) == 0:
            print(f"Error: No .md files found in directory: {path}", file=sys.stderr)
            sys.exit(1)
        if len(md_files) == 1:
            print(f"Auto-selected: {md_files[0].name}", file=sys.stderr)
            return str(md_files[0])
        # Multiple files — list them
        print(f"Multiple .md files found in {path}:", file=sys.stderr)
        for i, f in enumerate(md_files, 1):
            print(f"  {i}. {f.name}", file=sys.stderr)
        print(f"\nPlease specify the exact file path.", file=sys.stderr)
        sys.exit(1)

    print(f"Error: Path not found: {path}", file=sys.stderr)
    sys.exit(1)


def strip_notion_metadata(lines: list[str]) -> list[str]:
    """Remove Notion export metadata lines from the start of the file."""
    result = []
    in_metadata = True
    for line in lines:
        if in_metadata:
            stripped = line.strip()
            # Check if this looks like a metadata line (Key: Value)
            if stripped and ':' in stripped:
                key = stripped.split(':', 1)[0].strip()
                if key in NOTION_META_KEYS:
                    continue
            # Empty lines in metadata section are also skipped
            if not stripped and not result:
                continue
            in_metadata = False
        result.append(line)
    return result


def extract_title_and_body(content: str) -> tuple[str, str]:
    """Extract title from first H1 header and return (title, body)."""
    lines = content.split('\n')

    # Look for H1 in first 5 lines
    title = None
    title_line_idx = None
    for i, line in enumerate(lines[:5]):
        if line.startswith('# ') and not line.startswith('## '):
            title = line[2:].strip()
            title_line_idx = i
            break

    if title_line_idx is not None:
        # Remove title line and any immediately following blank line
        body_lines = lines[:title_line_idx] + lines[title_line_idx + 1:]
        # Strip leading blank lines
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        # Also strip any Notion metadata block that appears after the title
        body_lines = strip_notion_metadata(body_lines)
        body = '\n'.join(body_lines)
    else:
        body = content

    return title, body


def strip_image_references(content: str, source_dir: str = None) -> tuple[str, list[dict]]:
    """Remove image markdown references and return positions for later insertion.

    Returns (cleaned_content, image_list) where image_list contains
    {index, src, marker, resolved_path} for each image found.
    """
    images = []

    # Pattern 1: ![alt](url)
    for match in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', content):
        images.append({
            'original': match.group(0),
            'start': match.start(),
            'alt': match.group(1),
            'src': match.group(2),
        })

    # Pattern 2: ![[wikilink]]
    for match in re.finditer(r'!\[\[([^\]]+)\]\]', content):
        images.append({
            'original': match.group(0),
            'start': match.start(),
            'alt': '',
            'src': match.group(1),
        })

    # Deduplicate by start position (in case patterns overlap)
    seen_starts = set()
    unique_images = []
    for img in images:
        if img['start'] not in seen_starts:
            seen_starts.add(img['start'])
            unique_images.append(img)
    images = unique_images

    # Replace images with markers (process in reverse to preserve positions)
    cleaned = content
    for i, img in enumerate(sorted(images, key=lambda x: x['start'], reverse=True)):
        marker = f'[[IMG_{len(images) - i}]]'
        img['marker'] = marker
        cleaned = cleaned[:img['start']] + marker + cleaned[img['start'] + len(img['original']):]

    # Re-sort by position and assign final indices
    images.sort(key=lambda x: x['start'])
    for i, img in enumerate(images):
        img['index'] = i + 1
        img['marker'] = f'[[IMG_{i + 1}]]'
        # Try to resolve the image path relative to the source directory
        if source_dir:
            # Handle URL-encoded filenames (common in Notion exports)
            decoded_src = unquote(img['src'])
            candidate = os.path.join(source_dir, decoded_src)
            if os.path.isfile(candidate):
                img['resolved_path'] = os.path.abspath(candidate)
            else:
                # Also try the raw src
                candidate2 = os.path.join(source_dir, img['src'])
                if os.path.isfile(candidate2):
                    img['resolved_path'] = os.path.abspath(candidate2)
                else:
                    img['resolved_path'] = None
        else:
            img['resolved_path'] = None

    return cleaned, images


def escape_for_js(s: str) -> str:
    """Escape a string for embedding in a JS template literal (backtick string)."""
    s = s.replace('\\', '\\\\')    # backslashes first
    s = s.replace('`', '\\`')      # backticks
    s = s.replace('${', '\\${')    # template literal interpolation
    return s


def generate_paste_js(content: str) -> str:
    """Generate a self-contained JS IIFE that pastes markdown into Markdown Nice."""
    escaped = escape_for_js(content)
    return f"""(() => {{
  const md = `{escaped}`;
  const editor = document.querySelector('#nice-md-editor');
  if (!editor) return {{ success: false, error: '#nice-md-editor not found' }};

  const cmEl = editor.querySelector('.CodeMirror') || document.querySelector('.CodeMirror');
  const cm = cmEl?.CodeMirror;
  if (cm) {{
    cm.setValue(md);
    cm.refresh();
    cm.focus();
    cm.setCursor(cm.lineCount(), 0);
    if (typeof cm.save === 'function') cm.save();
    const textarea = cm.getTextArea?.() || cm.getInputField?.();
    if (textarea) {{
      textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
      textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }}
    return {{
      success: true,
      charCount: md.length,
      method: 'codemirror-setvalue',
      markerCount: (md.match(/\\[\\[IMG_\\d+\\]\\]/g) || []).length
    }};
  }}

  editor.focus();

  const dt = new DataTransfer();
  dt.setData('text/plain', md);
  const ev = new ClipboardEvent('paste', {{
    bubbles: true,
    cancelable: true,
    clipboardData: dt
  }});
  const pasteResult = editor.dispatchEvent(ev);

  const setNativeValue = (el, value) => {{
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : null;
    const descriptor = proto && Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) descriptor.set.call(el, value);
    else el.value = value;
  }};

  let method = 'paste-event';
  if (editor instanceof HTMLTextAreaElement || editor instanceof HTMLInputElement) {{
    if ((editor.value || '').length < Math.min(20, md.length)) {{
      setNativeValue(editor, md);
      editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
      editor.dispatchEvent(new Event('change', {{ bubbles: true }}));
      method = 'direct-value';
    }}
  }} else if ((editor.textContent || '').length < Math.min(20, md.length)) {{
    const textArea = editor.querySelector('textarea');
    if (textArea) {{
      setNativeValue(textArea, md);
      textArea.dispatchEvent(new Event('input', {{ bubbles: true }}));
      textArea.dispatchEvent(new Event('change', {{ bubbles: true }}));
      method = 'nested-textarea';
    }}
  }}

  return {{ success: true, charCount: md.length, method, pasteResult }};
}})()"""


def main():
    parser = argparse.ArgumentParser(description='Prepare Markdown for Markdown Nice editor')
    parser.add_argument('path', help='Path to Markdown file or directory containing .md files')
    parser.add_argument('--output', '-o', default='/tmp/mdnice_paste_content.js',
                        help='Output JS file path (default: /tmp/mdnice_paste_content.js)')
    parser.add_argument('--title', help='Override article title')
    parser.add_argument('--keep-images', action='store_true',
                        help='Keep image references in content (default: strip them)')
    parser.add_argument('--strip-metadata', action='store_true', default=True,
                        help='Strip Notion export metadata (default: true)')
    args = parser.parse_args()

    # Resolve file path (handles directory input)
    md_path = find_markdown_file(args.path)

    # Read content
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Strip metadata
    if args.strip_metadata:
        lines = content.split('\n')
        lines = strip_notion_metadata(lines)
        content = '\n'.join(lines)

    # Extract title
    title, body = extract_title_and_body(content)
    if args.title:
        title = args.title
    if not title:
        title = Path(md_path).stem  # Use filename as fallback

    # Handle images
    images = []
    source_dir = str(Path(md_path).parent)
    if not args.keep_images:
        body, images = strip_image_references(body, source_dir)

    # Check length
    if len(body) > 100000:
        print(f"WARNING: Content is {len(body)} chars, exceeds 100000 chars.",
              file=sys.stderr)

    # Generate JS
    js_code = generate_paste_js(body)

    # Write JS file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js_code)

    # Output summary as JSON to stdout
    result = {
        'title': title,
        'source_file': md_path,
        'content_chars': len(body),
        'js_file': str(output_path),
        'images': [{
            'index': img['index'],
            'marker': img['marker'],
            'src': img.get('src', ''),
            'resolved_path': img.get('resolved_path'),
        } for img in images],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
