# Format Platform Article Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `format-platform-article` skill that converts a local Markdown article and local media into a WeChat-first, multi-platform publish package.

**Architecture:** Add one focused Python CLI, `build_publish_package.py`, under a new skill directory. The CLI reads Markdown, normalizes local image paths into a portable `assets/` folder, optionally delegates table rendering to the existing `markdown-table-images` script, renders a magazine-style `wechat.html`, writes conservative platform Markdown variants, and emits `report.json`.

**Tech Stack:** Python 3 standard library, `unittest`, existing `skills/markdown-table-images/scripts/render_markdown_tables.py` for table images, skill metadata in `SKILL.md` and `evals/evals.json`.

---

## File Structure

- Create: `skills/format-platform-article/SKILL.md`
  - Skill workflow and guardrails for formatting local Markdown into publish packages.
- Create: `skills/format-platform-article/scripts/build_publish_package.py`
  - Single CLI and importable module for parsing, asset copying, rendering, reporting, and table conversion orchestration.
- Create: `skills/format-platform-article/templates/wechat_magazine.html`
  - Human-readable reference template for the magazine style. The CLI may keep rendering logic in Python, but this file documents the intended visual structure.
- Create: `skills/format-platform-article/templates/preview.html`
  - Human-readable reference for the local preview page wrapper.
- Create: `skills/format-platform-article/tests/test_build_publish_package.py`
  - Unit and smoke tests using `unittest`.
- Create: `skills/format-platform-article/tests/fixtures/article.md`
  - Fixture with H1/H2, local image, remote image, quote, code block, and table.
- Create: `skills/format-platform-article/tests/fixtures/media/sample.png`
  - Tiny fixture image.
- Create: `skills/format-platform-article/evals/evals.json`
  - Skill eval metadata covering package creation and compatibility handling.
- Modify: `README.md`
  - Add the new skill to the list and install commands.

## Task 1: Scaffold Skill And Fixtures

**Files:**
- Create: `skills/format-platform-article/SKILL.md`
- Create: `skills/format-platform-article/scripts/build_publish_package.py`
- Create: `skills/format-platform-article/tests/test_build_publish_package.py`
- Create: `skills/format-platform-article/tests/fixtures/article.md`
- Create: `skills/format-platform-article/tests/fixtures/media/sample.png`
- Create: `skills/format-platform-article/evals/evals.json`

- [ ] **Step 1: Create directories**

Run:

```bash
mkdir -p skills/format-platform-article/{scripts,templates,tests/fixtures/media,evals}
```

Expected: directories exist and `git status --short` shows `?? skills/format-platform-article/`.

- [ ] **Step 2: Create the fixture image**

Run:

```bash
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x8d\x9d\x1d\x00\x00\x00\x00IEND\xaeB`\x82' > skills/format-platform-article/tests/fixtures/media/sample.png
file skills/format-platform-article/tests/fixtures/media/sample.png
```

Expected: output includes `PNG image data`.

- [ ] **Step 3: Create fixture Markdown**

Create `skills/format-platform-article/tests/fixtures/article.md` with this content:

````markdown
# 多平台发布测试文章

这是一段开场文字，用来验证微信公众号杂志专栏风的正文节奏。

![本地图片](./media/sample.png)

## 核心结论

> 好的发布包应该先保证结构稳定，再考虑自动发布。

| 平台 | 首版策略 | 风险 |
| --- | --- | --- |
| 微信公众号 | 内联样式 HTML | 图片上传 |
| 知乎 | 保守 Markdown | HTML 清洗 |
| 今日头条 | 弱样式 Markdown | 表格渲染 |

```bash
python3 scripts/build_publish_package.py article.md --output article.publish
```

远程图片会被保留并进入报告：

![远程图片](https://example.com/remote.png)
````

Expected: file contains one H1, one local image, one table, one code block, and one remote image.

- [ ] **Step 4: Write the initial failing tests**

Create `skills/format-platform-article/tests/test_build_publish_package.py` with this content:

```python
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_publish_package  # noqa: E402


class BuildPublishPackageTests(unittest.TestCase):
    def test_extract_title_and_body_uses_h1(self):
        title, body, warnings = build_publish_package.extract_title_and_body("# 标题\n\n正文", Path("article.md"))

        self.assertEqual(title, "标题")
        self.assertEqual(body, "正文")
        self.assertEqual(warnings, [])

    def test_extract_title_and_body_uses_filename_without_h1(self):
        title, body, warnings = build_publish_package.extract_title_and_body("正文", Path("my-article.md"))

        self.assertEqual(title, "my-article")
        self.assertEqual(body, "正文")
        self.assertEqual(warnings[0]["code"], "missing_h1")

    def test_build_package_creates_expected_outputs(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(fixture, output, overwrite=False, strict=False, table_mode="never", style="magazine")

            self.assertEqual(result["title"], "多平台发布测试文章")
            self.assertTrue((output / "wechat.html").exists())
            self.assertTrue((output / "preview.html").exists())
            self.assertTrue((output / "copy.html").exists())
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertTrue((output / "platforms" / "toutiao.md").exists())
            self.assertTrue((output / "platforms" / "zsxq.md").exists())
            self.assertTrue((output / "platforms" / "smzdm.md").exists())
            self.assertTrue((output / "assets" / "sample.png").exists())
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tables"]["kept"], 1)
            self.assertIn("wechat.html", report["outputs"])
            self.assertTrue(any(item["code"] == "remote_image" for item in report["warnings"]))

    def test_existing_output_without_overwrite_fails(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            output.mkdir()

            with self.assertRaises(FileExistsError):
                build_publish_package.build_package(fixture, output, overwrite=False, strict=False, table_mode="never", style="magazine")

    def test_missing_local_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "article.md"
            source.write_text("# 标题\n\n![missing](./media/nope.png)\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                build_publish_package.build_package(source, root / "out", overwrite=False, strict=False, table_mode="never", style="magazine")

    def test_cli_smoke_writes_report_json(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            exit_code = build_publish_package.main([str(fixture), "--output", str(output), "--table-mode", "never"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run tests to verify they fail**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: FAIL with `ModuleNotFoundError: No module named 'build_publish_package'`.

- [ ] **Step 6: Create minimal script module**

Create `skills/format-platform-article/scripts/build_publish_package.py` with this content:

```python
#!/usr/bin/env python3
"""Build multi-platform article publish packages from local Markdown."""

from __future__ import annotations


def extract_title_and_body(text, source_path):
    raise NotImplementedError


def build_package(source_path, output_dir, overwrite=False, strict=False, table_mode="auto", style="magazine"):
    raise NotImplementedError


def main(argv=None):
    raise NotImplementedError
```

- [ ] **Step 7: Run tests to verify the failure moves to behavior**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 8: Commit scaffold**

Run:

```bash
git add skills/format-platform-article
git commit -m "feat(format-platform): scaffold article formatter skill"
```

Expected: commit succeeds and includes only the new scaffold files.

## Task 2: Implement Markdown Parsing, Warnings, And Asset Copying

**Files:**
- Modify: `skills/format-platform-article/scripts/build_publish_package.py`
- Modify: `skills/format-platform-article/tests/test_build_publish_package.py`

- [ ] **Step 1: Replace the script with parser and asset helpers**

Update `skills/format-platform-article/scripts/build_publish_package.py` so it contains these imports, constants, and helper functions:

```python
#!/usr/bin/env python3
"""Build multi-platform article publish packages from local Markdown."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
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


def strip_inline_markdown(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


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


def rewrite_images_to_assets(markdown: str, source_dir: Path, assets_dir: Path) -> tuple[str, list[dict[str, str]], list[dict[str, object]]]:
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
            warnings.append(warning("large_image", "Image is larger than 2 MB.", source=str(source), output=f"assets/{asset_name}"))
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
```

- [ ] **Step 2: Run discover to verify implemented parser tests pass**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: parser tests pass; package creation tests still fail because `build_package()` and `main()` are not implemented.

- [ ] **Step 3: Add a direct asset helper test**

Append this test method to `BuildPublishPackageTests`:

```python
    def test_rewrite_images_to_assets_copies_local_image(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            markdown, copied, warnings = build_publish_package.rewrite_images_to_assets(
                "![alt](./media/sample.png)",
                fixture_dir,
                assets,
            )

            self.assertEqual(markdown, "![alt](assets/sample.png)")
            self.assertTrue((assets / "sample.png").exists())
            self.assertEqual(copied[0]["output"], "assets/sample.png")
            self.assertEqual(warnings, [])
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: asset helper test passes; package creation tests still fail.

- [ ] **Step 5: Commit parser and asset helpers**

Run:

```bash
git add skills/format-platform-article/scripts/build_publish_package.py skills/format-platform-article/tests/test_build_publish_package.py
git commit -m "feat(format-platform): parse markdown and copy assets"
```

Expected: commit succeeds.

## Task 3: Implement WeChat HTML And Platform Markdown Rendering

**Files:**
- Modify: `skills/format-platform-article/scripts/build_publish_package.py`
- Create: `skills/format-platform-article/templates/wechat_magazine.html`
- Create: `skills/format-platform-article/templates/preview.html`
- Modify: `skills/format-platform-article/tests/test_build_publish_package.py`

- [ ] **Step 1: Add renderer helpers**

Append these functions before `build_package()` in `build_publish_package.py`:

```python
def markdown_inline_to_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#8a5a20;text-decoration:underline;">\1</a>', escaped)
    return escaped


def render_blocks(markdown: str, *, mode: str) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    quote_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(item.strip() for item in paragraph).strip()
            html_lines.append(
                '<p style="font-size:16px;line-height:2;margin:0 0 18px;color:#3f352c;">'
                + markdown_inline_to_html(text)
                + "</p>"
            )
            paragraph.clear()

    def flush_quote() -> None:
        if quote_lines:
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
    body = render_blocks(markdown, mode="wechat")
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
```

- [ ] **Step 2: Create template reference files**

Create `skills/format-platform-article/templates/wechat_magazine.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
</head>
<body style="margin:0;background:#f5f1ea;padding:24px 0;">
  <article style="max-width:720px;margin:0 auto;background:#fffdf8;padding:28px 22px;color:#2f2a24;font-family:Georgia,'PingFang SC','Hiragino Sans GB',serif;">
    {{ body }}
  </article>
</body>
</html>
```

Create `skills/format-platform-article/templates/preview.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Preview</title>
</head>
<body>
  <iframe src="wechat.html"></iframe>
</body>
</html>
```

- [ ] **Step 3: Add renderer tests**

Append this test method to `BuildPublishPackageTests`:

```python
    def test_render_wechat_html_contains_magazine_style(self):
        html = build_publish_package.render_wechat_html("标题", "## 小节\n\n> 引用")

        self.assertIn("background:#fffdf8", html)
        self.assertIn("<h1", html)
        self.assertIn("blockquote", html)
        self.assertIn("小节", html)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: renderer tests pass; package creation tests still fail because `build_package()` and `main()` are not implemented.

- [ ] **Step 5: Commit renderers**

Run:

```bash
git add skills/format-platform-article/scripts/build_publish_package.py skills/format-platform-article/templates skills/format-platform-article/tests/test_build_publish_package.py
git commit -m "feat(format-platform): render wechat and platform outputs"
```

Expected: commit succeeds.

## Task 4: Implement Package Builder And CLI

**Files:**
- Modify: `skills/format-platform-article/scripts/build_publish_package.py`
- Modify: `skills/format-platform-article/tests/test_build_publish_package.py`

- [ ] **Step 1: Add package builder functions**

Append or replace the existing `build_package()` and `main()` in `build_publish_package.py` with this implementation:

```python
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
    steps = ["Open preview.html and inspect the WeChat rendering.", "Use platforms/*.md for conservative platform-specific paste flows."]
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
        normalized, table_report, table_warnings = convert_tables_if_requested(normalized, output, table_mode)
        warnings.extend(table_warnings)

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
    parser.add_argument("--table-mode", choices=["auto", "always", "never"], default="auto", help="Table image conversion mode.")
    parser.add_argument("--style", choices=["magazine", "technical", "manual"], default="magazine", help="Visual style. First version supports magazine.")
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
    print(json.dumps({"output": str(Path(output).resolve()), "title": report["title"], "warnings": len(report["warnings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add a style validation test**

Append this test method to `BuildPublishPackageTests`:

```python
    def test_unsupported_style_fails(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_publish_package.build_package(fixture, Path(tmp) / "out", style="technical", table_mode="never")
```

- [ ] **Step 3: Run tests and inspect failures**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: tests fail with `NameError: name 'convert_tables_if_requested' is not defined` for any test using default `table_mode="auto"`, while `table_mode="never"` package tests pass.

- [ ] **Step 4: Temporarily verify no-table package path**

Run:

```bash
python3 skills/format-platform-article/scripts/build_publish_package.py \
  skills/format-platform-article/tests/fixtures/article.md \
  --output /tmp/format-platform-article.publish \
  --overwrite \
  --table-mode never
```

Expected: command prints JSON with `"title": "多平台发布测试文章"` and exits 0.

- [ ] **Step 5: Commit package builder**

Run:

```bash
git add skills/format-platform-article/scripts/build_publish_package.py skills/format-platform-article/tests/test_build_publish_package.py
git commit -m "feat(format-platform): build publish package outputs"
```

Expected: commit succeeds.

## Task 5: Integrate Table Image Conversion

**Files:**
- Modify: `skills/format-platform-article/scripts/build_publish_package.py`
- Modify: `skills/format-platform-article/tests/test_build_publish_package.py`

- [ ] **Step 1: Add table conversion implementation**

Add these imports near the top of `build_publish_package.py`:

```python
import subprocess
import tempfile
```

Add this function before `build_package()`:

```python
def markdown_table_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "markdown-table-images" / "scripts" / "render_markdown_tables.py"


def convert_tables_if_requested(markdown: str, output_dir: Path, table_mode: str) -> tuple[str, dict[str, object], list[dict[str, object]]]:
    table_count = count_pipe_tables(markdown)
    if table_count == 0:
        return markdown, {"converted": 0, "kept": 0, "mode": table_mode}, []

    script = markdown_table_script_path()
    if not script.exists():
        return markdown, {"converted": 0, "kept": table_count, "mode": table_mode}, [
            warning("table_converter_missing", "markdown-table-images renderer was not found.", script=str(script))
        ]

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

        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            return markdown, {"converted": 0, "kept": table_count, "mode": table_mode}, [
                warning("table_conversion_failed", "Table conversion failed; tables were kept as Markdown.", stderr=completed.stderr.strip())
            ]
        try:
            summary = json.loads(completed.stdout)
        except json.JSONDecodeError:
            summary = {"converted": 0, "kept": table_count}
        converted_markdown = output_path.read_text(encoding="utf-8")
        output_path.unlink(missing_ok=True)
        return converted_markdown, {
            "converted": int(summary.get("converted", 0)),
            "kept": int(summary.get("kept", 0)),
            "mode": table_mode,
        }, []
```

- [ ] **Step 2: Add table-mode never test**

Append this test method to `BuildPublishPackageTests`:

```python
    def test_table_mode_never_keeps_table_count(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(fixture, output, table_mode="never")

            self.assertEqual(result["tables"]["converted"], 0)
            self.assertEqual(result["tables"]["kept"], 1)
```

- [ ] **Step 3: Add default table conversion smoke test with dependency guard**

Append this test method to `BuildPublishPackageTests`:

```python
    def test_default_table_mode_reports_table_result(self):
        if shutil.which("uv") is None:
            self.skipTest("uv is required for table image conversion smoke test")
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(fixture, output, table_mode="auto")

            self.assertIn("converted", result["tables"])
            self.assertIn("kept", result["tables"])
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: PASS. If `uv` is missing, the default table conversion smoke test is skipped.

- [ ] **Step 5: Run default CLI smoke**

Run:

```bash
python3 skills/format-platform-article/scripts/build_publish_package.py \
  skills/format-platform-article/tests/fixtures/article.md \
  --output /tmp/format-platform-article.publish \
  --overwrite
```

Expected: command exits 0 and prints JSON. `/tmp/format-platform-article.publish/report.json` is valid.

- [ ] **Step 6: Validate report JSON**

Run:

```bash
python3 -m json.tool /tmp/format-platform-article.publish/report.json >/tmp/format-platform-article-report.json
```

Expected: command exits 0.

- [ ] **Step 7: Commit table integration**

Run:

```bash
git add skills/format-platform-article/scripts/build_publish_package.py skills/format-platform-article/tests/test_build_publish_package.py
git commit -m "feat(format-platform): integrate table image conversion"
```

Expected: commit succeeds.

## Task 6: Add Skill Documentation, Evals, And README Entry

**Files:**
- Create: `skills/format-platform-article/SKILL.md`
- Create: `skills/format-platform-article/evals/evals.json`
- Modify: `README.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/format-platform-article/SKILL.md` with this content:

```markdown
---
name: format-platform-article
description: Convert a local Markdown article and media folder into a WeChat-first multi-platform publish package. Use this skill after notion-to-md exports Markdown/media and before publishing to WeChat Official Account, Zhihu, Toutiao, Zsxq, SMZDM, or similar rich-text article platforms. Generates wechat.html, preview.html, copy.html, platform Markdown variants, assets, and report.json. Does not fetch Notion, log into platforms, copy to clipboard, or publish.
---

# Format Platform Article

Use this skill to turn a local Markdown article into a portable publish package for multiple Chinese content platforms.

## When To Use

- The source is already a local Markdown file.
- Images are local files beside the Markdown or under a local media folder.
- The user wants a good-looking WeChat Official Account version plus safer files for Zhihu, Toutiao, Zsxq, or SMZDM.
- The user wants formatting output before any browser publishing automation.

## Boundaries

This skill does not fetch Notion pages, upload images, write to the system clipboard, log into websites, create drafts, or publish posts.

Use `notion-to-md` first when the source is a Notion URL. Use `markdown-table-images` directly when the only request is table image conversion.

## Default Workflow

1. Identify the local Markdown file.
2. Choose an output directory. Default to `<article-stem>.publish` beside the source file.
3. Run the builder:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/format-platform-article/scripts/build_publish_package.py \
  /path/to/article.md \
  --output /path/to/article.publish
```

4. Open `preview.html` and inspect the WeChat rendering.
5. Check `report.json` for warnings before handing files to platform publishing skills.

## Output

```text
article.publish/
├── wechat.html
├── preview.html
├── copy.html
├── platforms/
│   ├── zhihu.md
│   ├── toutiao.md
│   ├── zsxq.md
│   └── smzdm.md
├── assets/
└── report.json
```

## Options

- `--overwrite`: replace an existing publish package.
- `--strict`: fail if compatibility warnings are detected.
- `--table-mode auto|always|never`: control table image conversion. Use `auto` by default.
- `--style magazine`: first-version default. Other styles are intentionally rejected until implemented.

## Error Handling

Fail on missing source files, missing local images, and output directory conflicts. Warn on remote images, large images, risky raw HTML, and table conversion failures unless `--strict` is set.
```

- [ ] **Step 2: Write evals**

Create `skills/format-platform-article/evals/evals.json` with this content:

```json
{
  "skill_name": "format-platform-article",
  "evals": [
    {
      "id": 1,
      "prompt": "把 notion-to-md 导出的 article.md 和 media 文件夹整理成一个微信公众号优先的多平台发布包，先不要自动复制或发布。",
      "expected_output": "生成 publish 包目录，包含 wechat.html、preview.html、copy.html、platforms/zhihu.md、platforms/toutiao.md、platforms/zsxq.md、platforms/smzdm.md、assets/ 和 report.json。",
      "files": ["article.md", "media/"]
    },
    {
      "id": 2,
      "prompt": "这篇 Markdown 里有表格和图片，要发公众号、知乎和今日头条，请把高风险表格处理成更稳的发布形态并输出兼容报告。",
      "expected_output": "使用默认 table-mode auto 生成发布包，表格转换结果写入 report.json，平台 Markdown 使用相对图片路径并保留图片位置。",
      "files": ["comparison.md", "media/"]
    },
    {
      "id": 3,
      "prompt": "我只想检查文章能不能安全发布，不想覆盖已有输出目录。",
      "expected_output": "如果输出目录已存在则停止并说明需要 --overwrite；如果使用 --strict，远程图片、风险 HTML 等兼容警告会让命令失败。",
      "files": ["article.md"]
    }
  ]
}
```

- [ ] **Step 3: Update README skill list**

Modify `README.md` under "Each directory under `skills/` is a standalone skill:" and add:

```markdown
- `format-platform-article` - format local Markdown/media into a WeChat-first multi-platform publish package.
```

Modify the install command block and add:

```bash
npx skills add backtomyfuture/agent-skills@format-platform-article -g -y
```

Modify the layout tree and add:

```text
    ├── format-platform-article/
```

- [ ] **Step 4: Validate JSON and compile Python**

Run:

```bash
python3 -m json.tool skills/format-platform-article/evals/evals.json >/tmp/format-platform-article-evals.json
python3 -m py_compile skills/format-platform-article/scripts/build_publish_package.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Run all skill tests**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: PASS.

- [ ] **Step 6: Commit docs and evals**

Run:

```bash
git add README.md skills/format-platform-article/SKILL.md skills/format-platform-article/evals/evals.json
git commit -m "docs(format-platform): document article formatter skill"
```

Expected: commit succeeds.

## Task 7: Final Verification And Cleanup

**Files:**
- Verify: all files under `skills/format-platform-article/`
- Verify: `README.md`

- [ ] **Step 1: Run compile check**

Run:

```bash
python3 -m py_compile skills/format-platform-article/scripts/*.py
```

Expected: exits 0.

- [ ] **Step 2: Run unit tests**

Run:

```bash
python3 -m unittest discover skills/format-platform-article/tests
```

Expected: all tests pass. A table conversion smoke test may be skipped only if `uv` is absent.

- [ ] **Step 3: Run end-to-end smoke**

Run:

```bash
rm -rf /tmp/format-platform-article.publish
python3 skills/format-platform-article/scripts/build_publish_package.py \
  skills/format-platform-article/tests/fixtures/article.md \
  --output /tmp/format-platform-article.publish \
  --overwrite
```

Expected: command exits 0 and prints JSON with the output path and title.

- [ ] **Step 4: Check output files**

Run:

```bash
test -s /tmp/format-platform-article.publish/wechat.html
test -s /tmp/format-platform-article.publish/preview.html
test -s /tmp/format-platform-article.publish/copy.html
test -s /tmp/format-platform-article.publish/platforms/zhihu.md
test -s /tmp/format-platform-article.publish/platforms/toutiao.md
test -s /tmp/format-platform-article.publish/platforms/zsxq.md
test -s /tmp/format-platform-article.publish/platforms/smzdm.md
test -s /tmp/format-platform-article.publish/assets/sample.png
python3 -m json.tool /tmp/format-platform-article.publish/report.json >/tmp/format-platform-article-report.json
```

Expected: every command exits 0.

- [ ] **Step 5: Inspect report summary**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('/tmp/format-platform-article.publish/report.json').read_text(encoding='utf-8'))
print(report['title'])
print(report['outputs'])
print(report['tables'])
print([item['code'] for item in report['warnings']])
PY
```

Expected:

```text
多平台发布测试文章
['wechat.html', 'preview.html', 'copy.html', 'platforms/zhihu.md', 'platforms/toutiao.md', 'platforms/zsxq.md', 'platforms/smzdm.md']
```

The table line contains `converted` and `kept`. The warning codes include `remote_image`.

- [ ] **Step 6: Check git diff**

Run:

```bash
git status --short
git diff --check
```

Expected: only intended files are modified or untracked; `git diff --check` exits 0.

- [ ] **Step 7: Commit final verification adjustments**

If Step 6 shows any small verification fixes, stage and commit them:

```bash
git add README.md skills/format-platform-article
git commit -m "test(format-platform): verify publish package generation"
```

Expected: commit succeeds only if there are changes. If there are no changes, skip this commit.

## Self-Review

Spec coverage:

- Local Markdown input: Task 1 fixture and Task 4 CLI.
- Local image resolution and asset copying: Task 2.
- WeChat inline-styled magazine HTML: Task 3.
- Preview and copy pages: Task 3 and Task 4.
- Platform Markdown variants: Task 3 and Task 4.
- Table image conversion via `markdown-table-images`: Task 5.
- Compatibility report: Task 4 and Task 7.
- Tests and eval metadata: Task 1, Task 6, Task 7.
- README install convention: Task 6.

Placeholder scan:

- The plan contains concrete file paths, commands, test code, and implementation snippets.
- No task depends on unspecified behavior or unnamed files.

Type consistency:

- Public functions used by tests are `extract_title_and_body`, `rewrite_images_to_assets`, `render_wechat_html`, `build_package`, and `main`.
- Report keys match the spec: `source`, `title`, `outputs`, `assets`, `tables`, `warnings`, `next_steps`.
