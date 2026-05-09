#!/usr/bin/env python3
"""Create Toutiao visual asset plan and HTML cards for a Markdown draft."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def strip_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def extract_title(lines: list[str], source: Path) -> tuple[str, list[str]]:
    for index, line in enumerate(lines):
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            title = strip_inline_markdown(match.group(1)) or source.stem
            return title, lines[:index] + lines[index + 1 :]
    for line in lines:
        plain = strip_inline_markdown(line)
        if plain:
            return plain[:40], lines
    return source.stem, lines


def text_blocks(lines: list[str]) -> list[str]:
    markdown = "\n".join(lines)
    markdown = IMAGE_RE.sub("", markdown)
    blocks = [strip_inline_markdown(part) for part in re.split(r"\n\s*\n", markdown)]
    return [b for b in blocks if len(b) >= 12]


def headings(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        match = re.match(r"^\s{0,3}#{2,4}\s+(.+?)\s*$", line)
        if match:
            result.append(strip_inline_markdown(match.group(1)))
    return result


def compact(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def split_points(text: str, count: int = 3) -> list[str]:
    pieces = re.split(r"[。！？!?；;]\s*", text)
    points = [compact(p, 34) for p in pieces if len(p.strip()) >= 8]
    return points[:count] or [compact(text, 34)]


def card_html(kind: str, title: str, subtitle: str, points: list[str]) -> str:
    point_items = "\n".join(f"<li>{html.escape(point)}</li>" for point in points)
    escaped_title = html.escape(compact(title, 34))
    escaped_subtitle = html.escape(compact(subtitle, 58))
    label = {"cover": "热点解读", "context": "关键信息", "takeaways": "结论速览"}.get(kind, kind)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #f4f5f7;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }}
  #card {{
    width: 1200px;
    height: 675px;
    padding: 64px 72px;
    background: linear-gradient(135deg, #102033 0%, #263848 48%, #f2b56b 100%);
    color: #fff;
    position: relative;
    overflow: hidden;
  }}
  #card::before {{
    content: "";
    position: absolute;
    inset: 42px;
    border: 1px solid rgba(255,255,255,.22);
  }}
  .label {{
    display: inline-block;
    padding: 8px 16px;
    border: 1px solid rgba(255,255,255,.55);
    font-size: 24px;
    letter-spacing: 0;
    margin-bottom: 42px;
  }}
  h1 {{
    margin: 0 0 26px;
    width: 900px;
    font-size: 58px;
    line-height: 1.12;
    font-weight: 760;
    letter-spacing: 0;
  }}
  .subtitle {{
    width: 760px;
    font-size: 30px;
    line-height: 1.45;
    opacity: .92;
  }}
  ul {{
    position: absolute;
    left: 72px;
    right: 72px;
    bottom: 58px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 18px;
    margin: 0;
    padding: 0;
    list-style: none;
  }}
  li {{
    min-height: 108px;
    padding: 22px 24px;
    background: rgba(255,255,255,.13);
    border: 1px solid rgba(255,255,255,.20);
    font-size: 24px;
    line-height: 1.38;
  }}
</style>
</head>
<body><section id="card">
  <div class="label">{html.escape(label)}</div>
  <h1>{escaped_title}</h1>
  <div class="subtitle">{escaped_subtitle}</div>
  <ul>{point_items}</ul>
</section></body>
</html>
"""


def insert_images(title: str, lines: list[str], visuals_dir_name: str) -> str:
    existing_images = sum(1 for line in lines if IMAGE_RE.search(line))
    output: list[str] = [f"# {title}", "", f"![封面图]({visuals_dir_name}/cover.png)", ""]
    body_lines = list(lines)

    paragraph_seen = 0
    inserted_context = False
    inserted_takeaways = False
    for line in body_lines:
        output.append(line)
        if line.strip() and not line.lstrip().startswith("#") and not IMAGE_RE.search(line):
            paragraph_seen += 1
        if not inserted_context and paragraph_seen >= 3:
            output.extend(["", f"![关键信息图]({visuals_dir_name}/inline-1.png)", ""])
            inserted_context = True
        if not inserted_takeaways and paragraph_seen >= 8:
            output.extend(["", f"![结论速览图]({visuals_dir_name}/inline-2.png)", ""])
            inserted_takeaways = True

    if not inserted_context:
        output.extend(["", f"![关键信息图]({visuals_dir_name}/inline-1.png)", ""])
    if not inserted_takeaways and existing_images == 0:
        output.extend(["", f"![结论速览图]({visuals_dir_name}/inline-2.png)", ""])
    return "\n".join(output).replace("\n\n\n", "\n\n").strip() + "\n"


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Toutiao visual HTML cards and a draft with image references.")
    parser.add_argument("source", help="Markdown draft path")
    parser.add_argument("--output-dir", required=True, help="Directory for visual plan and assets")
    parser.add_argument("--min-images", type=int, default=3, help="Minimum total images expected in the draft")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    visuals_dir = output_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    markdown = strip_frontmatter(source.read_text(encoding="utf-8-sig")).strip()
    lines = markdown.splitlines()
    title, body_lines = extract_title(lines, source)
    blocks = text_blocks(body_lines)
    h2s = headings(body_lines)

    subtitle = blocks[0] if blocks else title
    context_text = "。".join(h2s[:3]) if h2s else (blocks[1] if len(blocks) > 1 else subtitle)
    takeaway_text = blocks[-1] if blocks else subtitle

    specs = [
        {
            "id": "cover",
            "role": "cover",
            "html": visuals_dir / "cover.html",
            "png": visuals_dir / "cover.png",
            "title": title,
            "subtitle": subtitle,
            "points": split_points(context_text, 3),
        },
        {
            "id": "inline-1",
            "role": "context",
            "html": visuals_dir / "inline-1.html",
            "png": visuals_dir / "inline-1.png",
            "title": "这件事为什么重要",
            "subtitle": context_text,
            "points": split_points(subtitle, 3),
        },
        {
            "id": "inline-2",
            "role": "takeaways",
            "html": visuals_dir / "inline-2.html",
            "png": visuals_dir / "inline-2.png",
            "title": "读者该看什么",
            "subtitle": takeaway_text,
            "points": split_points(takeaway_text, 3),
        },
    ]

    for spec in specs:
        spec["html"].write_text(
            card_html(spec["role"], spec["title"], spec["subtitle"], spec["points"]),
            encoding="utf-8",
        )

    draft_with_visuals = output_dir / "draft_with_visuals.md"
    draft_with_visuals.write_text(insert_images(title, body_lines, "visuals"), encoding="utf-8")

    plan = {
        "source_file": str(source),
        "draft_with_visuals": str(draft_with_visuals),
        "min_images": args.min_images,
        "visuals": [
            {
                "id": spec["id"],
                "role": spec["role"],
                "html_file": str(spec["html"]),
                "png_file": str(spec["png"]),
                "open_url": file_url(spec["html"]),
                "render_command": f"agent-browser --session-name toutiao-visual --allow-file-access open '{file_url(spec['html'])}' && agent-browser --session-name toutiao-visual screenshot '#card' '{spec['png']}'",
            }
            for spec in specs
        ],
        "warnings": [
            "Render each HTML card to PNG before running prepare_toutiao_payload.py.",
            "If the article already has strong sourced images, keep them and use generated cards only as cover/context supplements.",
        ],
    }

    (output_dir / "visual_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
