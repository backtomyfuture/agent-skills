#!/usr/bin/env python3
"""Build a local-to-remote image URL map from copied Markdown Nice output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


IMG_TAG_RE = re.compile(r"<img\b[^>]*\bsrc=[\"'](https://[^\"']+)[\"'][^>]*>", re.IGNORECASE)
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https://[^)\s]+)(?:\s+\"[^\"]*\")?\)")
RAW_URL_RE = re.compile(r"https://[^\s\"'<>)]*?\.(?:png|jpe?g|gif|webp)(?:\?[^\s\"'<>)]*)?", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for pattern in (IMG_TAG_RE, MD_IMAGE_RE, RAW_URL_RE):
        for match in pattern.finditer(text):
            url = match.group(1) if pattern is not RAW_URL_RE else match.group(0)
            if url not in seen:
                urls.append(url)
                seen.add(url)
    return urls


def load_template(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Template must be a JSON object")
    return [str(key) for key in data.keys()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract HTTPS image URLs into a Zhihu remote image map.")
    parser.add_argument("--template", type=Path, required=True, help="zhihu-image-map.template.json")
    parser.add_argument("--source", type=Path, required=True, help="Copied Markdown Nice HTML/Markdown output containing remote image URLs")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON map")
    args = parser.parse_args(argv)

    keys = load_template(args.template)
    urls = extract_urls(args.source.read_text(encoding="utf-8"))
    if len(urls) < len(keys):
        print(
            f"ERROR: only found {len(urls)} remote image URLs, but template needs {len(keys)}.",
            file=sys.stderr,
        )
        return 1
    if len(urls) > len(keys):
        print(
            f"WARNING: found {len(urls)} remote image URLs; using the first {len(keys)} in source order.",
            file=sys.stderr,
        )

    mapping = {key: urls[index] for index, key in enumerate(keys)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "images": len(mapping)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
