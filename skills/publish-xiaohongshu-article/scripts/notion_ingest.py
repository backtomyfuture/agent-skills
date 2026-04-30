#!/usr/bin/env python3
"""
Ingest Markdown fetched from a Notion page, download remote inline images,
and rewrite image references to local files while preserving image positions.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

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
    req = urllib.request.Request(url, headers={'User-Agent': 'xhs-skill/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.headers.get('Content-Type')


def main() -> None:
    parser = argparse.ArgumentParser(description='Localize Notion Markdown images for Xiaohongshu publishing')
    parser.add_argument('--input', help='Markdown input file; defaults to stdin')
    parser.add_argument('--output-dir', required=True, help='Directory for article.md and downloaded images')
    args = parser.parse_args()

    md_text = Path(args.input).read_text(encoding='utf-8') if args.input else sys.stdin.read()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []

    def handle(match: re.Match) -> str:
        alt = match.group(1)
        url = match.group(2).strip()

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
            return f'![{alt}]({local_name})'
        except Exception as exc:
            print(f'WARN: failed to download image {idx} ({url}): {exc}', file=sys.stderr)
            images.append({
                'index': idx,
                'original_url': url,
                'local_path': None,
                'error': str(exc),
            })
            return match.group(0)

    rewritten = IMAGE_PATTERN.sub(handle, md_text)
    out_md = out_dir / 'article.md'
    out_md.write_text(rewritten, encoding='utf-8')

    result = {
        'output_file': str(out_md.resolve()),
        'output_dir': str(out_dir.resolve()),
        'image_count': len(images),
        'downloaded_count': sum(1 for img in images if img.get('local_path')),
        'failed_count': sum(1 for img in images if not img.get('local_path')),
        'images': images,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
