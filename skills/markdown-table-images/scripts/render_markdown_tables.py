#!/usr/bin/env python3
"""Render threshold-matching Markdown pipe tables as PNG images."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError as exc:  # pragma: no cover - dependency message
    raise SystemExit(
        "Missing dependency: Pillow. Install it in a virtual environment with "
        "`python -m pip install pillow`."
    ) from exc


SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
EMOJI_FONT_PATH = Path("/System/Library/Fonts/Apple Color Emoji.ttc")
EMOJI_PIXEL_SIZES = [20, 26, 32, 40, 48, 52, 64, 96, 160]


@dataclass
class TableBlock:
    start: int
    end: int
    headers: list[str]
    rows: list[list[str]]
    raw: list[str]
    heading: str | None

    @property
    def cols(self) -> int:
        return len(self.headers)

    @property
    def body_rows(self) -> int:
        return len(self.rows)

    @property
    def cells(self) -> int:
        return self.cols * max(1, self.body_rows)


@dataclass(frozen=True)
class TableTheme:
    name: str
    padding_x: int
    padding_y: int
    min_row_height: int
    border: int
    outer_padding: int
    background: str
    header_fill: str
    header_text: str
    row_fill: str
    alt_row_fill: str
    grid: str
    text: str
    # Optional editorial accent: an extra rule drawn just under the header row.
    # Skipped when header_accent_height <= 0. Used by the magazine theme to
    # mirror the "cream header + 2px terracotta underline" rule of the
    # WeChat magazine HTML template.
    header_accent_color: str = ""
    header_accent_height: int = 0


THEMES = {
    "plain": TableTheme(
        name="plain",
        padding_x=22,
        padding_y=16,
        min_row_height=64,
        border=2,
        outer_padding=0,
        background="#ffffff",
        header_fill="#f0f2f5",
        header_text="#1f2328",
        row_fill="#ffffff",
        alt_row_fill="#f8f9fb",
        grid="#d7dbe2",
        text="#1f2328",
    ),
    "publication": TableTheme(
        name="publication",
        padding_x=18,
        padding_y=13,
        min_row_height=54,
        border=1,
        outer_padding=16,
        background="#ffffff",
        header_fill="#111827",
        header_text="#ffffff",
        row_fill="#ffffff",
        alt_row_fill="#f8fafc",
        grid="#e5e7eb",
        text="#1f2937",
    ),
    # Warm magazine theme that matches the WeChat magazine HTML palette:
    # cream header, terracotta header text, soft warm zebra rows, and a
    # 2px terracotta underline below the header. Use this when the table
    # image will sit inside the format-platform-article wechat.html column
    # so the rasterized table doesn't look like a foreign engineering
    # screenshot pasted into an editorial layout.
    "magazine": TableTheme(
        name="magazine",
        padding_x=20,
        padding_y=14,
        min_row_height=58,
        border=1,
        outer_padding=18,
        background="#ffffff",
        header_fill="#fdf6ec",
        header_text="#7c2d12",
        row_fill="#ffffff",
        alt_row_fill="#fcf7ee",
        grid="#ece4d6",
        text="#2b2118",
        header_accent_color="#c2410c",
        header_accent_height=2,
    ),
}


def split_pipe_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            current.append(char)
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    if "|" not in lines[index]:
        return False
    return bool(SEPARATOR_RE.match(lines[index + 1]))


def normalize_row(row: list[str], cols: int) -> list[str]:
    if len(row) < cols:
        return row + [""] * (cols - len(row))
    return row[:cols]


def find_nearest_heading(lines: list[str], index: int) -> str | None:
    for line in reversed(lines[:index]):
        match = HEADING_RE.match(line)
        if match:
            return strip_inline_markdown(match.group(2))
    return None


def find_tables(text: str) -> tuple[list[str], list[TableBlock]]:
    lines = text.splitlines()
    tables: list[TableBlock] = []
    i = 0
    while i < len(lines):
        if not is_table_start(lines, i):
            i += 1
            continue

        start = i
        header = split_pipe_row(lines[i])
        i += 2
        rows: list[list[str]] = []
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            if SEPARATOR_RE.match(lines[i]):
                break
            rows.append(normalize_row(split_pipe_row(lines[i]), len(header)))
            i += 1

        if rows:
            tables.append(
                TableBlock(
                    start=start,
                    end=i,
                    headers=header,
                    rows=rows,
                    raw=lines[start:i],
                    heading=find_nearest_heading(lines, start),
                )
            )
        else:
            i = start + 1

    return lines, tables


def strip_inline_markdown(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\\|", "|")
    return text.strip()


def should_convert(table: TableBlock, min_rows: int, min_cols: int, min_cells: int, mode: str) -> bool:
    checks = [
        table.body_rows >= min_rows,
        table.cols >= min_cols,
        table.cells >= min_cells,
    ]
    if mode == "all":
        return all(checks)
    return any(checks)


def candidate_fonts() -> list[Path]:
    return [
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]


def load_font(size: int, font_path: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [Path(font_path)] if font_path else candidate_fonts()
    for path in paths:
        if path and path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    if not EMOJI_FONT_PATH.exists():
        return None
    best_size = min(EMOJI_PIXEL_SIZES, key=lambda candidate: (abs(candidate - size), candidate < size))
    try:
        return ImageFont.truetype(str(EMOJI_FONT_PATH), size=best_size)
    except OSError:
        return None


def is_emoji_base(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2B00 <= codepoint <= 0x2BFF
    )


def take_emoji_cluster(text: str, index: int) -> tuple[str, int]:
    end = index + 1
    while end < len(text):
        char = text[end]
        codepoint = ord(char)
        if codepoint in (0xFE0E, 0xFE0F) or 0x1F3FB <= codepoint <= 0x1F3FF:
            end += 1
            continue
        if char == "\u200d" and end + 1 < len(text):
            end += 2
            continue
        break
    return text[index:end], end


def split_emoji_segments(text: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    normal: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_emoji_base(char):
            if normal:
                segments.append(("".join(normal), False))
                normal = []
            cluster, index = take_emoji_cluster(text, index)
            segments.append((cluster, True))
            continue
        normal.append(char)
        index += 1
    if normal:
        segments.append(("".join(normal), False))
    return segments


def single_line_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None = None,
) -> tuple[int, int]:
    if not text:
        text = " "
    width = 0
    height = 0
    for segment, is_emoji in split_emoji_segments(text):
        active_font = emoji_font if is_emoji and emoji_font is not None else font
        bbox = draw.textbbox((0, 0), segment, font=active_font, embedded_color=is_emoji and emoji_font is not None)
        width += bbox[2] - bbox[0]
        height = max(height, bbox[3] - bbox[1])
    return width, height


def text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None = None,
    spacing: int = 6,
) -> tuple[int, int]:
    lines = text.splitlines() or [" "]
    sizes = [single_line_size(draw, line, font, emoji_font) for line in lines]
    width = max((size[0] for size in sizes), default=0)
    height = sum(size[1] for size in sizes) + spacing * max(0, len(lines) - 1)
    return width, height


def draw_text_with_emoji(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    fill: str,
    spacing: int,
) -> None:
    x_start, y = xy
    for line in text.splitlines() or [""]:
        line_width, line_height = text_size(draw, line, font, emoji_font, spacing=spacing)
        del line_width
        x = x_start
        for segment, is_emoji in split_emoji_segments(line):
            active_font = emoji_font if is_emoji and emoji_font is not None else font
            draw.text(
                (x, y),
                segment,
                fill=fill,
                font=active_font,
                embedded_color=is_emoji and emoji_font is not None,
            )
            segment_width, _ = single_line_size(draw, segment, active_font)
            x += segment_width
        y += line_height + spacing


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    emoji_font: ImageFont.ImageFont | None = None,
) -> str:
    text = strip_inline_markdown(text)
    wrapped_lines: list[str] = []
    for source_line in text.splitlines() or [""]:
        current = ""
        for char in source_line:
            trial = current + char
            width, _ = text_size(draw, trial, font, emoji_font)
            if width <= max_width or not current:
                current = trial
            else:
                wrapped_lines.append(current)
                current = char
        wrapped_lines.append(current)
    return "\n".join(wrapped_lines)


def estimate_col_widths(
    draw: ImageDraw.ImageDraw,
    table: TableBlock,
    font: ImageFont.ImageFont,
    header_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    max_width: int,
    padding_x: int,
) -> list[int]:
    cols = table.cols
    min_width = 130
    max_col_width = 520
    widths: list[int] = []
    for col in range(cols):
        values = [table.headers[col]] + [row[col] for row in table.rows]
        measured = []
        for value in values:
            plain = strip_inline_markdown(value)
            sample = max(plain.splitlines() or [plain], key=len, default="")
            font_for_value = header_font if value == table.headers[col] else font
            width, _ = text_size(draw, sample, font_for_value, emoji_font)
            measured.append(width + padding_x * 2)
        widths.append(min(max(max(measured, default=min_width), min_width), max_col_width))

    available = max_width - 2
    total = sum(widths)
    if total > available:
        scale = available / total
        widths = [max(95, math.floor(width * scale)) for width in widths]
    return widths


def should_center_column(table: TableBlock, col_index: int) -> bool:
    values = [table.headers[col_index]] + [row[col_index] for row in table.rows]
    plain_values = [strip_inline_markdown(value).replace(" ", "") for value in values]
    return all(len(value) <= 8 for value in plain_values)


def render_table(
    table: TableBlock,
    output_path: Path,
    font_path: str | None = None,
    max_width: int = 1400,
    font_size: int = 24,
    scale: int = 2,
    theme_name: str = "publication",
) -> None:
    theme = THEMES[theme_name]
    font = load_font(font_size, font_path)
    header_font = load_font(font_size, font_path)
    emoji_font = load_emoji_font(font_size)
    padding_x = theme.padding_x
    padding_y = theme.padding_y
    border = theme.border

    scratch = Image.new("RGB", (10, 10), "white")
    draw = ImageDraw.Draw(scratch)
    col_widths = estimate_col_widths(draw, table, font, header_font, emoji_font, max_width, padding_x)

    wrapped_rows: list[list[str]] = []
    wrapped_header = [
        wrap_text(draw, cell, header_font, col_widths[index] - padding_x * 2, emoji_font)
        for index, cell in enumerate(table.headers)
    ]
    wrapped_rows.append(wrapped_header)
    for row in table.rows:
        wrapped_rows.append(
            [
                wrap_text(draw, cell, font, col_widths[index] - padding_x * 2, emoji_font)
                for index, cell in enumerate(row)
            ]
        )

    row_heights: list[int] = []
    for row_index, row in enumerate(wrapped_rows):
        active_font = header_font if row_index == 0 else font
        heights = [text_size(draw, cell, active_font, emoji_font)[1] + padding_y * 2 for cell in row]
        row_heights.append(max(max(heights), theme.min_row_height))

    width = sum(col_widths) + border
    height = sum(row_heights) + border
    canvas_width = width + theme.outer_padding * 2
    canvas_height = height + theme.outer_padding * 2
    image = Image.new("RGB", (canvas_width * scale, canvas_height * scale), theme.background)
    draw = ImageDraw.Draw(image)

    def s(value: int) -> int:
        return value * scale

    font_scaled = load_font(font_size * scale, font_path)
    header_font_scaled = load_font(font_size * scale, font_path)
    emoji_font_scaled = load_emoji_font(font_size * scale)

    center_columns = [should_center_column(table, index) for index in range(table.cols)]

    y = theme.outer_padding
    for row_index, row in enumerate(wrapped_rows):
        x = theme.outer_padding
        fill = theme.header_fill if row_index == 0 else (theme.row_fill if row_index % 2 else theme.alt_row_fill)
        active_font = header_font_scaled if row_index == 0 else font_scaled
        text_fill = theme.header_text if row_index == 0 else theme.text
        for col_index, cell in enumerate(row):
            cell_w = col_widths[col_index]
            cell_h = row_heights[row_index]
            draw.rectangle([s(x), s(y), s(x + cell_w), s(y + cell_h)], fill=fill, outline=theme.grid, width=s(border))
            text_width, text_height = text_size(draw, cell, active_font, emoji_font_scaled, spacing=s(6))
            text_x = s(x + padding_x)
            if center_columns[col_index]:
                text_x = s(x) + max(0, (s(cell_w) - text_width) // 2)
            text_y = s(y + padding_y)
            if "\n" not in cell:
                text_y = s(y) + max(0, (s(cell_h) - text_height) // 2)
            draw_text_with_emoji(
                draw,
                (text_x, text_y),
                cell,
                active_font,
                emoji_font_scaled,
                text_fill,
                s(6),
            )
            x += cell_w
        # Editorial header accent: draw a thin colored bar across the bottom
        # of the header row. Only when the theme opts in (magazine).
        if (
            row_index == 0
            and theme.header_accent_height > 0
            and theme.header_accent_color
        ):
            accent_h = s(theme.header_accent_height)
            accent_y_bottom = s(y + row_heights[row_index])
            draw.rectangle(
                [
                    s(theme.outer_padding),
                    accent_y_bottom - accent_h,
                    s(theme.outer_padding + sum(col_widths)),
                    accent_y_bottom,
                ],
                fill=theme.header_accent_color,
            )
        y += row_heights[row_index]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def slugify(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    text = strip_inline_markdown(value).lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_-]+", "", text)
    return text[:40].strip("-_") or fallback


def relative_link(target: Path, markdown_path: Path) -> str:
    base = markdown_path.parent.resolve()
    return str(target.resolve().relative_to(base)).replace("\\", "/")


def replace_tables(
    input_path: Path,
    output_path: Path,
    image_dir: Path,
    min_rows: int,
    min_cols: int,
    min_cells: int,
    threshold_mode: str,
    font: str | None,
    max_width: int,
    font_size: int,
    theme_name: str,
    dry_run: bool,
) -> dict[str, object]:
    text = input_path.read_text(encoding="utf-8")
    lines, tables = find_tables(text)
    converted: list[dict[str, object]] = []
    kept = 0
    replacements: dict[int, list[str]] = {}

    output_abs = output_path.resolve()
    image_dir_abs = (output_abs.parent / image_dir).resolve() if not image_dir.is_absolute() else image_dir.resolve()

    for table_index, table in enumerate(tables, start=1):
        if not should_convert(table, min_rows, min_cols, min_cells, threshold_mode):
            kept += 1
            continue

        label = table.heading or f"表格 {table_index}"
        filename = f"table_{table_index:02d}_{slugify(label, f'table-{table_index}')}.png"
        image_path = image_dir_abs / filename
        if not dry_run:
            render_table(table, image_path, font_path=font, max_width=max_width, font_size=font_size, theme_name=theme_name)

        image_link = relative_link(image_path, output_abs)
        replacement = [f"![{label}]({image_link})"]
        replacements[table.start] = replacement
        for line_index in range(table.start + 1, table.end):
            replacements[line_index] = []
        converted.append(
            {
                "table_index": table_index,
                "start_line": table.start + 1,
                "rows": table.body_rows,
                "cols": table.cols,
                "cells": table.cells,
                "image": image_link,
                "label": label,
            }
        )

    output_lines: list[str] = []
    for index, line in enumerate(lines):
        if index in replacements:
            output_lines.extend(replacements[index])
        else:
            output_lines.append(line)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    return {
        "input": str(input_path),
        "output": str(output_path),
        "image_dir": str(image_dir_abs),
        "tables_found": len(tables),
        "converted": len(converted),
        "kept": kept,
        "threshold_mode": threshold_mode,
        "theme": theme_name,
        "converted_tables": converted,
        "dry_run": dry_run,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Markdown file to process.")
    parser.add_argument("--output", type=Path, help="Output Markdown path. Defaults to INPUT.tables-as-images.md.")
    parser.add_argument("--image-dir", type=Path, default=Path("media/tables"), help="Image directory relative to output Markdown.")
    parser.add_argument("--min-rows", type=int, default=4, help="Convert when body row count is at least this value.")
    parser.add_argument("--min-cols", type=int, default=3, help="Convert when column count is at least this value.")
    parser.add_argument("--min-cells", type=int, default=12, help="Convert when rows * cols is at least this value.")
    parser.add_argument("--threshold-mode", choices=["any", "all"], default="any", help="Convert when any threshold matches, or only when all thresholds match.")
    parser.add_argument("--font", help="Optional TrueType/OpenType font path.")
    parser.add_argument("--max-width", type=int, default=1400, help="Maximum PNG width before high-DPI scaling.")
    parser.add_argument("--font-size", type=int, default=24, help="Base font size before high-DPI scaling.")
    parser.add_argument("--theme", choices=sorted(THEMES), default="publication", help="Visual theme for rendered table images. Choices: plain, publication, magazine.")
    parser.add_argument("--backup", action="store_true", help="When output equals input, create INPUT.bak first.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be converted without writing files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    output_path = args.output.resolve() if args.output else input_path.with_name(f"{input_path.stem}.tables-as-images{input_path.suffix}")

    if output_path == input_path and args.backup and not args.dry_run:
        backup_path = input_path.with_suffix(input_path.suffix + ".bak")
        shutil.copy2(input_path, backup_path)
    elif output_path == input_path and not args.backup and not args.dry_run:
        raise SystemExit("Refusing in-place overwrite without --backup.")

    summary = replace_tables(
        input_path=input_path,
        output_path=output_path,
        image_dir=args.image_dir,
        min_rows=args.min_rows,
        min_cols=args.min_cols,
        min_cells=args.min_cells,
        threshold_mode=args.threshold_mode,
        font=args.font,
        max_width=args.max_width,
        font_size=args.font_size,
        theme_name=args.theme,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
