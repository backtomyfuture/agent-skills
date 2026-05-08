#!/usr/bin/env python3
"""Build multi-platform article publish packages from local Markdown."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
RAW_HTML_RISK_RE = re.compile(r"<\s*(script|style|iframe|object|embed)\b|class\s*=", re.IGNORECASE)
REMOTE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
LARGE_IMAGE_BYTES = 2 * 1024 * 1024
PLATFORMS = ("zhihu", "toutiao", "zsxq", "smzdm")


def warning(code: str, message: str, **extra: object) -> dict[str, object]:
    item: dict[str, object] = {"code": code, "message": message}
    item.update(extra)
    return item


def strip_inline_markdown(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def extract_title_and_body(text: str, source_path: Path) -> tuple[str, str, list[dict[str, object]]]:
    clean = text.lstrip("\ufeff")
    lines = clean.splitlines()
    warnings: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s{0,3}#\s+(.+?)\s*$", line)
        if match:
            title = strip_inline_markdown(match.group(1))
            body_lines = lines[:index] + lines[index + 1 :]
            body = "\n".join(body_lines).strip()
            return title, body, warnings
    title = source_path.stem
    warnings.append(warning("missing_h1", "No H1 heading found; using filename as title.", source=str(source_path)))
    return title, clean.strip(), warnings


def clean_image_target(target: str) -> str:
    value = target.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value


def unique_asset_name(assets_dir: Path, source: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-") or "asset"
    suffix = source.suffix or ".bin"
    candidate = f"{stem}{suffix}"
    counter = 2
    while (assets_dir / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def rewrite_images_to_assets(
    markdown: str,
    source_dir: Path,
    assets_dir: Path,
) -> tuple[str, list[dict[str, str]], list[dict[str, object]]]:
    copied: list[dict[str, str]] = []
    warnings: list[dict[str, object]] = []
    assets_dir.mkdir(parents=True, exist_ok=True)

    def replace(match: re.Match[str]) -> str:
        alt = match.group(1)
        raw_target = clean_image_target(match.group(2))
        if REMOTE_RE.match(raw_target):
            warnings.append(warning("remote_image", "Remote image was left unchanged.", target=raw_target))
            return match.group(0)

        source = (source_dir / raw_target).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Local image not found: {raw_target}")

        asset_name = unique_asset_name(assets_dir, source)
        output = assets_dir / asset_name
        shutil.copy2(source, output)
        if output.stat().st_size > LARGE_IMAGE_BYTES:
            warnings.append(
                warning("large_image", "Image is larger than 2 MB.", source=str(source), output=f"assets/{asset_name}")
            )
        copied.append({"source": str(source), "output": f"assets/{asset_name}"})
        return f"![{alt}](assets/{asset_name})"

    return IMAGE_RE.sub(replace, markdown), copied, warnings


def count_pipe_tables(markdown: str) -> int:
    lines = markdown.splitlines()
    count = 0
    for index in range(len(lines) - 1):
        if "|" in lines[index] and TABLE_SEPARATOR_RE.match(lines[index + 1]):
            count += 1
    return count


def detect_raw_html_warnings(markdown: str) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if RAW_HTML_RISK_RE.search(line):
            warnings.append(warning("raw_html_risk", "Raw HTML may be stripped by platform editors.", line=line_number))
    return warnings


def markdown_inline_to_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#8a5a20;text-decoration:underline;">\1</a>',
        escaped,
    )
    return escaped


def render_blocks(markdown: str) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    quote_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph).strip()
        html_lines.append(
            '<p style="font-size:16px;line-height:2;margin:0 0 18px;color:#3f352c;">'
            + markdown_inline_to_html(text)
            + "</p>"
        )
        paragraph.clear()

    def flush_quote() -> None:
        if not quote_lines:
            return
        text = " ".join(quote_lines).strip()
        html_lines.append(
            '<blockquote style="margin:22px 0;padding:14px 16px;background:#f6efe3;'
            'border-left:4px solid #b7791f;color:#5f4b32;font-size:15px;line-height:1.9;">'
            + markdown_inline_to_html(text)
            + "</blockquote>"
        )
        quote_lines.clear()

    for line in lines:
        if line.startswith("```"):
            if in_code:
                html_lines.append(
                    '<pre style="background:#292524;color:#f8fafc;border-radius:8px;padding:14px;'
                    'overflow:auto;font-size:13px;line-height:1.7;margin:18px 0;">'
                    + html.escape("\n".join(code_lines))
                    + "</pre>"
                )
                code_lines.clear()
                in_code = False
            else:
                flush_paragraph()
                flush_quote()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            flush_quote()
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            flush_quote()
            level = len(heading.group(1))
            text = markdown_inline_to_html(heading.group(2).strip())
            if level == 2:
                html_lines.append(
                    '<h2 style="font-size:21px;line-height:1.5;margin:34px 0 16px;color:#2f2a24;'
                    'font-weight:700;border-bottom:1px solid #e7dac6;padding-bottom:8px;">'
                    + text
                    + "</h2>"
                )
            else:
                html_lines.append(
                    '<h3 style="font-size:18px;line-height:1.6;margin:26px 0 12px;color:#4b4036;font-weight:700;">'
                    + text
                    + "</h3>"
                )
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            flush_paragraph()
            flush_quote()
            alt = html.escape(image.group(1))
            src = html.escape(clean_image_target(image.group(2)))
            html_lines.append(
                '<figure style="margin:24px 0;text-align:center;">'
                f'<img src="{src}" alt="{alt}" style="max-width:100%;height:auto;border-radius:6px;" />'
                f'<figcaption style="font-size:12px;color:#8a8175;margin-top:8px;">{alt}</figcaption>'
                "</figure>"
            )
            continue

        if line.lstrip().startswith(">"):
            flush_paragraph()
            quote_lines.append(line.lstrip()[1:].strip())
            continue

        paragraph.append(line)

    flush_paragraph()
    flush_quote()
    if in_code and code_lines:
        html_lines.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
    return "\n".join(html_lines)


def render_wechat_html(title: str, markdown: str) -> str:
    body = render_blocks(markdown)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
</head>
<body style="margin:0;background:#f5f1ea;padding:24px 0;">
  <article style="max-width:720px;margin:0 auto;background:#fffdf8;padding:28px 22px;color:#2f2a24;font-family:Georgia,'PingFang SC','Hiragino Sans GB',serif;">
    <h1 style="font-size:26px;line-height:1.35;margin:0;color:#2f2a24;font-weight:700;">{safe_title}</h1>
    <div style="width:48px;height:3px;background:#b7791f;margin:16px 0 28px;"></div>
    {body}
  </article>
</body>
</html>
"""


def render_preview_html(title: str, wechat_html: str, report_path: str) -> str:
    safe_title = html.escape(title)
    escaped = html.escape(wechat_html)
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Preview - {safe_title}</title></head>
<body style="margin:0;background:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;">
  <header style="padding:16px 20px;background:#111827;color:#fff;">
    <strong>{safe_title}</strong>
    <span style="margin-left:12px;color:#cbd5e1;">Report: {html.escape(report_path)}</span>
  </header>
  <iframe src="wechat.html" style="display:block;width:100%;height:calc(100vh - 56px);border:0;background:#fff;"></iframe>
  <details style="padding:16px 20px;background:#fff;"><summary>wechat.html source</summary><pre>{escaped}</pre></details>
</body>
</html>
"""


def render_copy_html(title: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Copy - {safe_title}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;padding:24px;">
  <h1>{safe_title}</h1>
  <p>首版只生成发布包文件，不自动写入系统剪贴板。请先打开 <a href="preview.html">preview.html</a> 检查效果。</p>
  <iframe src="wechat.html" style="display:block;width:100%;height:80vh;border:1px solid #ddd;"></iframe>
</body>
</html>
"""


def markdown_for_platform(markdown: str, platform: str) -> str:
    text = markdown
    text = re.sub(r"<\s*(script|style|iframe|object|embed)\b.*?</\s*\1\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<section[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</section>", "", text, flags=re.IGNORECASE)
    if platform in {"toutiao", "smzdm"}:
        text = re.sub(r"<span[^>]*>(.*?)</span>", r"\1", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip() + "\n"


def rewrite_asset_paths_for_platforms(markdown: str) -> str:
    return markdown.replace("](assets/", "](../assets/")


def markdown_table_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "markdown-table-images" / "scripts" / "render_markdown_tables.py"


def convert_tables_if_requested(
    markdown: str,
    output_dir: Path,
    table_mode: str,
) -> tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, str]]]:
    table_count = count_pipe_tables(markdown)
    if table_count == 0:
        return markdown, {"converted": 0, "kept": 0, "mode": table_mode}, [], []

    script = markdown_table_script_path()
    if not script.exists():
        return markdown, {"converted": 0, "kept": table_count, "mode": table_mode}, [
            warning("table_converter_missing", "markdown-table-images renderer was not found.", script=str(script))
        ], []

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        input_path = tmpdir / "table-input.md"
        output_path = output_dir / ".table-normalized.md"
        input_path.write_text(markdown, encoding="utf-8")

        command = [
            "uv",
            "run",
            "--with",
            "pillow",
            "python",
            str(script),
            str(input_path),
            "--output",
            str(output_path),
            "--image-dir",
            "assets/tables",
            "--theme",
            "publication",
        ]
        if table_mode == "always":
            command.extend(["--min-rows", "1", "--min-cols", "2", "--min-cells", "2"])

        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
        except FileNotFoundError as exc:
            return markdown, {"converted": 0, "kept": table_count, "mode": table_mode}, [
                warning(
                    "table_conversion_failed",
                    "Table conversion failed because uv or python was not available; tables were kept as Markdown.",
                    stderr=str(exc),
                )
            ], []
        if completed.returncode != 0:
            return markdown, {"converted": 0, "kept": table_count, "mode": table_mode}, [
                warning(
                    "table_conversion_failed",
                    "Table conversion failed; tables were kept as Markdown.",
                    stderr=completed.stderr.strip(),
                )
            ], []
        try:
            summary = json.loads(completed.stdout)
        except json.JSONDecodeError:
            summary = {"converted": 0, "kept": table_count, "converted_tables": []}
        converted_markdown = output_path.read_text(encoding="utf-8")
        output_path.unlink(missing_ok=True)
        table_assets = [
            {"source": "generated_table", "output": str(item["image"])}
            for item in summary.get("converted_tables", [])
            if isinstance(item, dict) and item.get("image")
        ]
        return converted_markdown, {
            "converted": int(summary.get("converted", 0)),
            "kept": int(summary.get("kept", 0)),
            "mode": table_mode,
        }, [], table_assets


def ensure_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory exists: {output_dir}")
        shutil.rmtree(output_dir)
    (output_dir / "platforms").mkdir(parents=True, exist_ok=True)
    (output_dir / "assets").mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_next_steps(warnings: list[dict[str, object]]) -> list[str]:
    steps = [
        "Open preview.html and inspect the WeChat rendering.",
        "Use platforms/*.md for conservative platform-specific paste flows.",
    ]
    if warnings:
        steps.append("Review report.json warnings before publishing.")
    return steps


def build_package(
    source_path: Path | str,
    output_dir: Path | str,
    overwrite: bool = False,
    strict: bool = False,
    table_mode: str = "auto",
    style: str = "magazine",
) -> dict[str, object]:
    source = Path(source_path).resolve()
    output = Path(output_dir).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source Markdown not found: {source}")
    if style != "magazine":
        raise ValueError("Only --style magazine is supported in the first version.")
    if table_mode not in {"auto", "always", "never"}:
        raise ValueError("--table-mode must be auto, always, or never")

    ensure_output_dir(output, overwrite=overwrite)
    source_text = source.read_text(encoding="utf-8-sig")
    title, body, warnings = extract_title_and_body(source_text, source)
    normalized, assets, image_warnings = rewrite_images_to_assets(body, source.parent, output / "assets")
    warnings.extend(image_warnings)
    warnings.extend(detect_raw_html_warnings(normalized))

    table_report = {"converted": 0, "kept": count_pipe_tables(normalized), "mode": table_mode}
    if table_mode != "never":
        normalized, table_report, table_warnings, table_assets = convert_tables_if_requested(normalized, output, table_mode)
        warnings.extend(table_warnings)
        assets.extend(table_assets)

    if strict and warnings:
        codes = ", ".join(str(item["code"]) for item in warnings)
        raise RuntimeError(f"Strict mode failed with warnings: {codes}")

    wechat_html = render_wechat_html(title, normalized)
    write_text(output / "wechat.html", wechat_html)
    write_text(output / "preview.html", render_preview_html(title, wechat_html, "report.json"))
    write_text(output / "copy.html", render_copy_html(title))

    platform_outputs: list[str] = []
    platform_markdown = rewrite_asset_paths_for_platforms(normalized)
    for platform in PLATFORMS:
        relative = f"platforms/{platform}.md"
        write_text(output / relative, markdown_for_platform(platform_markdown, platform))
        platform_outputs.append(relative)

    outputs = ["wechat.html", "preview.html", "copy.html", *platform_outputs]
    report: dict[str, object] = {
        "source": str(source),
        "title": title,
        "outputs": outputs,
        "assets": assets,
        "tables": table_report,
        "warnings": warnings,
        "next_steps": build_next_steps(warnings),
    }
    write_text(output / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a multi-platform article publish package.")
    parser.add_argument("source", type=Path, help="Source Markdown file.")
    parser.add_argument("--output", type=Path, help="Output publish package directory.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory.")
    parser.add_argument("--strict", action="store_true", help="Fail when compatibility warnings are detected.")
    parser.add_argument(
        "--table-mode",
        choices=["auto", "always", "never"],
        default="auto",
        help="Table image conversion mode.",
    )
    parser.add_argument(
        "--style",
        choices=["magazine", "technical", "manual"],
        default="magazine",
        help="Visual style. First version supports magazine.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or args.source.with_suffix(".publish")
    try:
        report = build_package(
            args.source,
            output,
            overwrite=args.overwrite,
            strict=args.strict,
            table_mode=args.table_mode,
            style=args.style,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"output": str(Path(output).resolve()), "title": report["title"], "warnings": len(report["warnings"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
