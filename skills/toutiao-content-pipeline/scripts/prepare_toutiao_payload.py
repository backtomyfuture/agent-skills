#!/usr/bin/env python3
"""Prepare a Markdown draft for Toutiao browser staging."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def clean_link_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return target


def is_remote(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https", "data"}


def resolve_image(source_file: Path, target: str) -> Path | None:
    target = clean_link_target(target)
    if is_remote(target):
        return None
    parsed = urlparse(target)
    path_text = unquote(parsed.path or target)
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = source_file.parent / path
    return path.resolve()


def extract_title(markdown: str, source_file: Path, override: str | None) -> tuple[str, str]:
    if override:
        return override.strip(), markdown

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            title = strip_inline_markdown(match.group(1)).strip()
            remaining = lines[:index] + lines[index + 1 :]
            return title, "\n".join(remaining).strip()

    for line in lines:
        stripped = strip_inline_markdown(line).strip()
        if stripped:
            return stripped[:60], markdown

    return source_file.stem, markdown


def strip_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    return text


def replace_images(markdown: str, source_file: Path) -> tuple[str, list[dict[str, object]]]:
    images: list[dict[str, object]] = []

    def repl(match: re.Match[str]) -> str:
        index = len(images) + 1
        alt = match.group(1).strip()
        src = clean_link_target(match.group(2))
        resolved = resolve_image(source_file, src)
        marker = f"[[IMG_{index}]]"
        exists = bool(resolved and resolved.exists())
        images.append(
            {
                "index": index,
                "alt": alt,
                "src": src,
                "resolved_path": str(resolved) if resolved else None,
                "marker": marker,
                "exists": exists,
            }
        )
        return f"\n{marker}\n"

    return IMAGE_RE.sub(repl, markdown), images


def markdown_to_toutiao_text(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")

    # Convert links before stripping punctuation-like markdown.
    text = LINK_RE.sub(lambda m: f"{m.group(1)}（{m.group(2)}）", text)

    out_lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            out_lines.append(line)
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading:
            out_lines.append(strip_inline_markdown(heading.group(1)).strip())
            continue

        line = re.sub(r"^\s{0,3}>\s?", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "- ", line)
        line = re.sub(r"^\s*(\d+)[.)]\s+", r"\1. ", line)
        line = strip_inline_markdown(line)
        out_lines.append(line.strip())

    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n" if text else ""


def slugify(path: Path) -> str:
    stem = path.stem.strip() or "toutiao-draft"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return slug or "toutiao-draft"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Toutiao payload files from Markdown.")
    parser.add_argument("source", help="Markdown draft path")
    parser.add_argument("--mode", choices=["article", "weitoutiao", "auto"], default="auto")
    parser.add_argument("--title", help="Override title")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--max-micro-chars", type=int, default=1800)
    parser.add_argument("--copy-source", action="store_true", help="Copy the source markdown into output-dir")
    args = parser.parse_args()

    source_file = Path(args.source).expanduser().resolve()
    if not source_file.exists():
        raise SystemExit(f"Source file not found: {source_file}")

    raw = source_file.read_text(encoding="utf-8-sig")
    markdown = strip_frontmatter(raw).strip()
    title, body_markdown = extract_title(markdown, source_file, args.title)
    body_with_markers, images = replace_images(body_markdown, source_file)
    body_text = markdown_to_toutiao_text(body_with_markers)

    mode = args.mode
    warnings: list[str] = []
    if mode == "auto":
        mode = "weitoutiao" if len(body_text) <= args.max_micro_chars and not title else "article"

    if mode == "weitoutiao" and title:
        first_line = title.strip()
        if first_line and not body_text.lstrip().startswith(first_line):
            body_text = f"{first_line}\n\n{body_text}".strip() + "\n"

    if mode == "weitoutiao" and len(body_text) > args.max_micro_chars:
        warnings.append(
            f"weitoutiao body is {len(body_text)} chars, over recommended max {args.max_micro_chars}; split or switch to article"
        )

    missing_images = [img for img in images if not img["exists"]]
    for img in missing_images:
        warnings.append(f"missing image {img['marker']}: {img['src']}")

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path("/tmp/toutiao-content-pipeline") / slugify(source_file)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    title_file = output_dir / "title.txt"
    body_file = output_dir / "body.txt"
    payload_file = output_dir / "payload.json"

    write_text(title_file, title.strip() + "\n")
    write_text(body_file, body_text)

    if args.copy_source:
        shutil.copy2(source_file, output_dir / source_file.name)

    payload = {
        "source_file": str(source_file),
        "mode": mode,
        "title": title.strip(),
        "title_file": str(title_file),
        "body_file": str(body_file),
        "body_chars": len(body_text),
        "images": images,
        "warnings": warnings,
    }
    payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
