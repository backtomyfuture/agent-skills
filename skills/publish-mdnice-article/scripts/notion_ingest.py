#!/usr/bin/env python3
"""
Ingest a Notion page's Markdown (from the notion-fetch MCP tool), download
all inline images to a local directory, and rewrite image references to
point at those local copies.

The output is a self-contained directory that prepare_content.py can consume
just like any other local Markdown folder — image positions in the body are
preserved exactly because we only rewrite the URL portion of each
`![alt](url)` reference, leaving its position in the text untouched.

Usage:
    # Read Markdown from stdin
    cat notion_raw.md | python3 notion_ingest.py --output-dir /tmp/mdnice-notion

    # Read from a file
    python3 notion_ingest.py --input notion_raw.md --output-dir /tmp/mdnice-notion

Output layout:
    <output_dir>/article.md    — markdown with image refs rewritten to local paths
    <output_dir>/img_1.png     — downloaded images, numbered by position in source
    <output_dir>/img_2.jpg
    ...

Prints JSON summary to stdout with the output file path and image list.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Matches standard Markdown image syntax: ![alt](url)
# Non-greedy on alt so nested square brackets don't confuse the regex.
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

EXT_BY_MIME = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/bmp': '.bmp',
    'image/tiff': '.tiff',
}

SUPPORTED_EXTS = set(EXT_BY_MIME.values()) | {'.jpeg'}


def infer_extension(url: str, content_type: str | None) -> str:
    """Pick a sensible file extension from Content-Type first, URL path second."""
    if content_type:
        ct = content_type.split(';')[0].strip().lower()
        if ct in EXT_BY_MIME:
            return EXT_BY_MIME[ct]
    parsed = urllib.parse.urlparse(url)
    suffix = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
    if suffix in SUPPORTED_EXTS:
        return '.jpg' if suffix == '.jpeg' else suffix
    return '.png'


def download(url: str) -> tuple[bytes, str | None]:
    """Fetch a URL and return (bytes, content_type). Raises on network errors."""
    req = urllib.request.Request(url, headers={'User-Agent': 'mdnice-skill/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.headers.get('Content-Type')


def main():
    parser = argparse.ArgumentParser(description='Ingest Notion Markdown + images for Markdown Nice')
    parser.add_argument('--input', help='Markdown input file (default: read stdin)')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to write article.md and downloaded images into')
    args = parser.parse_args()

    md_text = (Path(args.input).read_text(encoding='utf-8')
               if args.input else sys.stdin.read())

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []

    def handle(match: re.Match) -> str:
        alt = match.group(1)
        url = match.group(2).strip()

        # Already a local path — leave as-is.
        if not (url.startswith('http://') or url.startswith('https://')):
            return match.group(0)

        idx = len(images) + 1
        try:
            data, content_type = download(url)
            ext = infer_extension(url, content_type)
            local_name = f'img_{idx}{ext}'
            dest = out_dir / local_name
            dest.write_bytes(data)
            images.append({
                'index': idx,
                'original_url': url,
                'local_path': str(dest.resolve()),
                'bytes': len(data),
            })
            # Rewrite the URL portion only — position in text is preserved.
            return f'![{alt}]({local_name})'
        except Exception as e:
            print(f'WARN: failed to download image {idx} ({url}): {e}', file=sys.stderr)
            images.append({
                'index': idx,
                'original_url': url,
                'local_path': None,
                'error': str(e),
            })
            # Keep the original reference; prepare_content.py will flag the
            # resolved_path as null and the skill will warn the user.
            return match.group(0)

    rewritten = IMAGE_PATTERN.sub(handle, md_text)

    out_md = out_dir / 'article.md'
    out_md.write_text(rewritten, encoding='utf-8')

    result = {
        'output_file': str(out_md.resolve()),
        'output_dir': str(out_dir.resolve()),
        'image_count': len(images),
        'downloaded_count': sum(1 for i in images if i.get('local_path')),
        'failed_count': sum(1 for i in images if not i.get('local_path')),
        'images': images,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
