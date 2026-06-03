#!/usr/bin/env python3
"""Build multi-platform article publish packages from local Markdown."""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
UNORDERED_LIST_RE = re.compile(r"^\s{0,3}[-*+]\s+(.+?)\s*$")
ORDERED_LIST_RE = re.compile(r"^\s{0,3}\d+[.)]\s+(.+?)\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
RAW_HTML_RISK_RE = re.compile(r"<\s*(script|style|iframe|object|embed)\b|class\s*=", re.IGNORECASE)
REMOTE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
LARGE_IMAGE_BYTES = 2 * 1024 * 1024
REMOTE_IMAGE_TIMEOUT_SECONDS = 30
REMOTE_IMAGE_MAX_BYTES = 25 * 1024 * 1024
REMOTE_IMAGE_USER_AGENT = "format-platform-article/1.0 (+https://factory.ai)"
REMOTE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
PLATFORMS = ("zhihu", "toutiao", "zsxq", "smzdm")
# Zhihu is intentionally NOT in RICH_HTML_PLATFORMS: it is produced as an
# import-ready Markdown file (platforms/zhihu.md) by md2zhihu, not as
# paste-ready HTML. Zsxq is also special-cased later because its editor handles
# low-style native tags better than the shared magazine wrapper.
RICH_HTML_PLATFORMS = ("toutiao", "zsxq", "smzdm")
PLATFORM_PROFILES: dict[str, dict[str, object]] = {
    "zhihu": {
        "label": "知乎",
        "recommended": "platforms/zhihu.md",
        "fallback": "assets/ + image-manifest.md",
        "output_format": "markdown",
        "html_image_mode": "markdown",
        "editor_model": "知乎写文章编辑器支持导入/粘贴 Markdown。md2zhihu 生成的单文件 Markdown 把图片托管到 Git 图床、公式转知乎原生公式图、表格转 HTML，可一键导入。",
        "image_strategy": "由 md2zhihu 把本地图片推送到 Git 图床（gitee/github）并改写成 HTTPS 原始链接，无需知乎 Cookie。若未配置 --zhihu-asset-repo 或未安装 md2zhihu，则回退为带本地 ../assets/ 链接的 zhihu.md，并按 image-manifest.md 手工补图。",
        "code_strategy": "md2zhihu 保留原生代码块（可选转为图片）；公式 $...$/$$...$$ 转成知乎公式图，mermaid/graphviz 代码块转为图片。",
        "notes": [
            "标题在知乎文章标题框单独填写；zhihu.md 只负责正文，不带 H1、包装头或平台说明文字。",
            "知乎正文通过“导入文档/粘贴 Markdown”载入 platforms/zhihu.md。",
            "图片走 Git 图床：需要一个有写权限的公共仓库（gitee/github）并通过 SSH key 或带令牌的 https 仓库地址配置 --zhihu-asset-repo。",
            "md2zhihu 依赖 pandoc/imagemagick/node/mermaid-cli，且不支持 Windows。",
            "LaTeX 公式、mermaid、graphviz 会自动转成知乎可显示的图片。",
        ],
        "sources": [
            {
                "label": "md2zhihu（markdown 转知乎兼容格式）",
                "url": "https://github.com/drmingdrmer/md2zhihu",
            },
            {
                "label": "md2zhihu 中文说明",
                "url": "https://github.com/drmingdrmer/md2zhihu/blob/main/README-cn.md",
            },
        ],
    },
    "toutiao": {
        "label": "今日头条",
        "recommended": "platforms/toutiao.html",
        "fallback": "assets/ + image-manifest.md",
        "html_image_mode": "data",
        "editor_model": "头条号图文富文本编辑器，电脑端入口为“主页 - 创作 - 图文”。",
        "image_strategy": "复制 toutiao.html 的富文本结构，图片已用 Base64 内嵌；若平台拒绝内嵌图片，再按 image-manifest.md 从 assets/ 兜底上传。",
        "code_strategy": "代码块保留为原生 pre/code，不加外层样式和语言标签，避免头条编辑器清洗后把配置压成一行。",
        "notes": [
            "标题在头条号图文编辑器的标题框单独填写；toutiao.html 只负责正文，不带 H1、包装头或平台说明文字。",
            "平台支持图文发布、文章链接和扩展链接，但外链/内链建议发布前在编辑器里单独复核。",
            "减少复杂表格和深层样式；头条支持原生引用，重点段落保留为 blockquote；预算类小表格转成清单，长配置优先保留代码块而不是压成一行。",
        ],
        "sources": [
            {
                "label": "头条创作者帮助中心 - 图文创作",
                "url": "https://baike.toutiao.com/detail/211/212/214",
            },
        ],
    },
    "zsxq": {
        "label": "知识星球",
        "recommended": "platforms/zsxq.html",
        "fallback": "assets/ + image-manifest.md",
        "html_image_mode": "data",
        "editor_model": "网页端长文章，官方说明支持 100000 字符、图文混排、超链接和一些 Markdown 语法。",
        "image_strategy": "复制 zsxq.html 的富文本结构，图片已用 Base64 内嵌；若平台拒绝内嵌图片，再按 image-manifest.md 从 assets/ 兜底上传。",
        "code_strategy": "代码块保留为原生 pre/code，避免复杂内联样式被知识星球清洗后变形。",
        "notes": [
            "长文走网页版“长文章”，不要用 App 主题流承载长教程。",
            "zsxq.html 刻意不使用公众号杂志卡片、背景和复杂 inline style；标题、段落、列表、代码块尽量保留为平台更稳的原生结构。",
            "高价值段落使用文本安全的 ▍ 标记；如果图片被清洗，再按 image-manifest.md 从 assets/ 手工补传。",
            "如果链接被吞或样式异常，改用完整裸链接或编辑器内插入超链接。",
        ],
        "sources": [
            {
                "label": "知识星球常见问题 - 发布长文章",
                "url": "https://doc.zsxq.com/faq/faqs.html",
            },
        ],
    },
    "smzdm": {
        "label": "什么值得买",
        "recommended": "platforms/smzdm.html",
        "fallback": "assets/ + image-manifest.md",
        "html_image_mode": "data",
        "editor_model": "原创投稿富文本编辑器，强调头图、H2/H3、商品/文章卡片、引用、链接和图片。",
        "image_strategy": "复制 smzdm.html 的富文本结构，图片已用 Base64 内嵌；若平台拒绝内嵌图片，再按 image-manifest.md 从 assets/ 兜底上传。商品链接发布前改成编辑器内“插入卡片”。",
        "code_strategy": "保留代码块，但什么值得买不偏代码阅读，复杂配置前后加解释，避免整篇像文档。",
        "notes": [
            "H2/H3 只用于真正层级，不要当加粗使用；商品购买链接必须优先改成卡片。",
            "评测/晒物类内容至少准备清晰头图和多张正文图，发布前补分类、标签和商品链接。",
        ],
        "sources": [
            {
                "label": "什么值得买文章投稿规范",
                "url": "https://post.smzdm.com/about",
            },
            {
                "label": "什么值得买官方账号投稿指引",
                "url": "https://www.toutiao.com/zixun/7543077851290601518/",
            },
        ],
    },
}
CALLOUT_MARKERS = {
    "📖": ("导读", "#fdf6ec", "#c2410c", "#7c2d12"),
    "⚠️": ("注意", "#fdf6ec", "#c2410c", "#7c2d12"),
    "💡": ("提示", "#fdf6ec", "#c2410c", "#7c2d12"),
    "✅": ("完成", "#f4f7f4", "#15803d", "#14532d"),
    "🎯": ("重点", "#fef7e6", "#b45309", "#7c2d12"),
    "😱": ("震撼", "#fdf6ec", "#c2410c", "#7c2d12"),
    "🤯": ("亲历", "#fdf6ec", "#c2410c", "#7c2d12"),
    "🎁": ("福利", "#fef7e6", "#b45309", "#7c2d12"),
    "🔥": ("热门", "#fdf6ec", "#c2410c", "#7c2d12"),
    "🚀": ("推荐", "#fdf6ec", "#c2410c", "#7c2d12"),
    "📌": ("置顶", "#fdf6ec", "#c2410c", "#7c2d12"),
    "📣": ("通知", "#fdf6ec", "#c2410c", "#7c2d12"),
    "❤️": ("推荐", "#fdf6ec", "#c2410c", "#7c2d12"),
    "🧰": ("工具", "#fdf6ec", "#c2410c", "#7c2d12"),
    "📏": ("口径", "#fdf6ec", "#c2410c", "#7c2d12"),
    "🟢": ("绿灯", "#f4f7f4", "#15803d", "#14532d"),
    "🟡": ("黄灯", "#fef7e6", "#b45309", "#7c2d12"),
    "🔴": ("红灯", "#fef2f2", "#dc2626", "#7f1d1d"),
}
CODE_PLACEHOLDERS = {
    "UUID": "UUID",
    "SNI": "SNI",
    "PUBLIC-KEY": "PUBLIC-KEY",
    "SHORT-ID": "SHORT-ID",
    "备注": "备注",
    "服务器IP": "服务器IP",
    "你的服务器IP": "服务器IP",
    "你的UUID": "UUID",
    "你的PUBLIC-KEY": "PUBLIC-KEY",
    "你的SHORT-ID": "SHORT-ID",
}
CODE_PLACEHOLDER_STYLE = (
    "display:inline-block;margin:0 1px;padding:0 3px;border-radius:4px;"
    "background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;font-weight:700;"
    "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;"
    "font-size:0.92em;line-height:1.35;white-space:nowrap;"
)
ZSXQ_QUOTE_MARKER = "▍"
ZSXQ_PARAGRAPH_STYLE = "margin:0 0 1.05em;line-height:1.85;font-size:16px;color:#1f2937;"
ZSXQ_QUOTE_STYLE = "margin:1.15em 0;line-height:1.85;font-size:16px;color:#111827;"
ZSXQ_HEADING_STYLE = "margin:2.1em 0 0.85em;line-height:1.42;font-size:1.35em;font-weight:800;color:#111827;"
ZSXQ_IMAGE_STYLE = "display:block;max-width:100%;height:auto;margin:1.2em auto 0;border-radius:6px;"
ZSXQ_CAPTION_STYLE = "margin:0.35em 0 1.25em;text-align:center;color:#6b7280;font-size:13px;line-height:1.6;"
# Image-caption paragraphs look like "*▼ caption*" or "▼ caption" — they sit just below
# an image and describe it. Detect them so they get pill-style caption styling instead of
# leaking raw asterisks into the rendered output.
IMAGE_CAPTION_RE = re.compile(r"^\*?\s*([▼▲►◀↓↑→←▷◁])\s+(.+?)\s*\*?$")


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


def _remote_image_extension(url: str, content_type: str | None) -> str:
    """Pick a sane file extension for a downloaded image.

    Notion presigned URLs include the original filename in the path (e.g.
    `.../image.png?X-Amz-...`), so the URL path almost always carries a
    correct extension. We still fall back to the response Content-Type and
    finally to `.png` so the asset name is always usable.
    """
    try:
        path = urlparse(url).path
    except ValueError:
        path = ""
    ext = Path(path).suffix.lower()
    if ext in REMOTE_IMAGE_EXTENSIONS:
        return ext
    if content_type:
        primary = content_type.split(";", 1)[0].strip().lower()
        guess = mimetypes.guess_extension(primary) or ""
        if guess == ".jpe":
            guess = ".jpg"
        if guess in REMOTE_IMAGE_EXTENSIONS:
            return guess
    return ".png"


def _unique_remote_asset_name(assets_dir: Path, index: int, ext: str) -> str:
    candidate = f"remote_{index:02d}{ext}"
    counter = 2
    while (assets_dir / candidate).exists():
        candidate = f"remote_{index:02d}-{counter}{ext}"
        counter += 1
    return candidate


def download_remote_image(url: str, assets_dir: Path, index: int) -> Path | None:
    """Download a remote image into ``assets_dir`` and return the local path.

    Returns ``None`` when the download fails for any reason (timeout, HTTP
    error, response too large, malformed URL). The caller is expected to
    fall back to leaving the original Markdown URL in place and emit a
    descriptive warning so the user can intervene.
    """
    if not REMOTE_RE.match(url):
        return None
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": REMOTE_IMAGE_USER_AGENT,
                "Accept": "image/*,application/octet-stream;q=0.9,*/*;q=0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=REMOTE_IMAGE_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type")
            data = response.read(REMOTE_IMAGE_MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    if not data or len(data) > REMOTE_IMAGE_MAX_BYTES:
        return None

    ext = _remote_image_extension(url, content_type)
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_name = _unique_remote_asset_name(assets_dir, index, ext)
    output = assets_dir / asset_name
    output.write_bytes(data)
    return output


def rewrite_images_to_assets(
    markdown: str,
    source_dir: Path,
    assets_dir: Path,
    download_remote: bool = True,
    remote_downloader: Optional[Callable[[str, Path, int], Optional[Path]]] = None,
) -> tuple[str, list[dict[str, str]], list[dict[str, object]]]:
    """Materialize every Markdown image reference into ``assets_dir``.

    Local images are copied. Remote (`http(s)://...`) URLs are fetched when
    ``download_remote`` is True so wechat/toutiao/zsxq/smzdm.html can embed
    them as Base64 and zhihu.md can reference a stable local path. This is
    especially important for Notion exports whose S3 presigned URLs expire
    within an hour and would otherwise turn every cross-platform output
    into a pile of broken `<img>` tags.
    """
    copied: list[dict[str, str]] = []
    warnings: list[dict[str, object]] = []
    assets_dir.mkdir(parents=True, exist_ok=True)
    fetch = remote_downloader or download_remote_image
    remote_counter = {"value": 0}

    def replace(match: re.Match[str]) -> str:
        alt = match.group(1)
        raw_target = clean_image_target(match.group(2))
        if REMOTE_RE.match(raw_target):
            if not download_remote:
                warnings.append(warning("remote_image", "Remote image was left unchanged.", target=raw_target))
                return match.group(0)
            remote_counter["value"] += 1
            local = fetch(raw_target, assets_dir, remote_counter["value"])
            if local is None:
                warnings.append(
                    warning(
                        "remote_image_download_failed",
                        "Failed to download remote image; leaving URL in place.",
                        target=raw_target,
                    )
                )
                return match.group(0)
            asset_name = local.name
            try:
                size = local.stat().st_size
            except OSError:
                size = 0
            if size > LARGE_IMAGE_BYTES:
                warnings.append(
                    warning(
                        "large_image",
                        "Image is larger than 2 MB.",
                        source=raw_target,
                        output=f"assets/{asset_name}",
                    )
                )
            copied.append({"source": raw_target, "output": f"assets/{asset_name}"})
            return f"![{alt}](assets/{asset_name})"

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


def normalize_notion_quote_callouts(markdown: str) -> str:
    """Remove Notion's nested quote separator from emoji callout lines.

    Notion often exports callouts as `> 📖 > **导读**：...`. The second `>`
    is not authored punctuation; if it survives, every platform shows a stray
    greater-than sign in the lead paragraph. Limit the cleanup to known emoji
    callout markers so real nested blockquotes remain untouched.
    """
    markers = "|".join(re.escape(marker) for marker in CALLOUT_MARKERS)
    pattern = re.compile(rf"^(\s{{0,3}}>\s*)({markers})\s+>\s+", re.MULTILINE)
    return pattern.sub(r"\1\2 ", markdown)


def markdown_inline_to_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(
        r"`([^`]+)`",
        r'<code style="font-size:0.9em;background:#faf3e7;color:#9a3412;border:1px solid #f0e3c8;border-radius:4px;padding:1px 6px;font-family:Menlo,Consolas,monospace;">\1</code>',
        escaped,
    )
    escaped = re.sub(
        r"\*\*([^*]+)\*\*",
        r'<span style="color:#1a1a1a;font-weight:700;border-bottom:2px solid #fcd34d;padding-bottom:1px;">\1</span>',
        escaped,
    )
    # Italic: single * not adjacent to other * or word chars (avoids tripping on **bold** leftovers).
    escaped = re.sub(
        r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])",
        r'<em style="color:#5a5a5a;font-style:italic;">\1</em>',
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#9a3412;text-decoration:none;border-bottom:1px solid #fcd34d;padding-bottom:1px;">\1</a>',
        escaped,
    )
    label_colon_re = re.compile(r'(<span style="[^"]+font-weight:700;?[^"]*">)([^<]+)(</span>)\s*([：:])\s*')

    def keep_label_colon_together(match: re.Match[str]) -> str:
        suffix = "&nbsp;" if match.end() < len(escaped) else ""
        return f"{match.group(1)}{match.group(2)}{match.group(4)}{match.group(3)}{suffix}"

    escaped = label_colon_re.sub(keep_label_colon_together, escaped)
    return escaped


def markdown_inline_to_editor_html(text: str) -> str:
    """Render only conservative inline markup for non-WeChat rich-text editors."""
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    # Italic via single * — must run after **bold** so the lookbehind/lookahead
    # have something concrete to skip past. Editors that strip <em> degrade
    # gracefully to plain text, which is still better than leaking raw `*`.
    escaped = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    label_colon_re = re.compile(r"(<strong>)([^<]+)(</strong>)\s*([：:])\s*")

    def keep_label_colon_together(match: re.Match[str]) -> str:
        suffix = "&nbsp;" if match.end() < len(escaped) else ""
        return f"{match.group(1)}{match.group(2)}{match.group(4)}{match.group(3)}{suffix}"

    escaped = label_colon_re.sub(keep_label_colon_together, escaped)
    return escaped


def strip_caption_wrapper(text: str) -> tuple[str, str] | None:
    """If `text` is an image-caption paragraph like '*▼ caption*', return
    (arrow, caption_body). Otherwise return None.

    Used by every platform renderer so we don't ship raw markdown asterisks
    into Zhihu / Toutiao / Zsxq / SMZDM HTML where they look like a typo.
    """
    match = IMAGE_CAPTION_RE.match(text.strip())
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def render_editor_image_caption(text: str) -> str:
    """A safe centered, italic, small caption for non-WeChat rich text editors.

    These editors aggressively strip CSS, so we use a plain centered <p>
    with <em> rather than the WeChat-style pill. The arrow stays inline so
    the reader still gets the visual cue pointing at the image above.
    """
    parsed = strip_caption_wrapper(text)
    if not parsed:
        return ""
    arrow, body = parsed
    inner = markdown_inline_to_editor_html(body)
    return (
        '<p style="text-align:center;color:#6b7280;font-size:14px;margin:0 0 18px;">'
        f"<em>{html.escape(arrow)} {inner}</em>"
        "</p>"
    )


def parse_callout(text: str) -> tuple[str, str, str]:
    marker = next((item for item in CALLOUT_MARKERS if text.startswith(item)), "")
    label, _, _, _ = CALLOUT_MARKERS.get(marker, ("提示", "", "", ""))
    body = text[len(marker) :].strip() if marker else text.strip()
    body = re.sub(r"^>\s+", "", body)
    if marker:
        bold_match = re.match(r"^\*\*\s*([^*\n]+?)\s*\*\*\s*[:：]?\s*", body)
        if bold_match:
            custom_label = bold_match.group(1).strip()
            if custom_label:
                label = custom_label
                body = body[bold_match.end():]
        else:
            body = re.sub(
                r"^\*\*\s*" + re.escape(label) + r"\s*\*\*\s*[:：]?\s*",
                "",
                body,
            )
    return marker, label, body.strip()


def extract_outline(markdown: str, limit: int = 6) -> list[str]:
    headings: list[str] = []
    in_code = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 2:
            headings.append(strip_inline_markdown(match.group(2)))
            if len(headings) >= limit:
                break
    return headings


def estimate_reading_minutes(markdown: str) -> int:
    plain = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    plain = IMAGE_RE.sub("", plain)
    plain = re.sub(r"[#>*_`|\-\[\]()]|https?://\S+", " ", plain)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", plain)
    latin_words = re.findall(r"[A-Za-z0-9_+-]+", plain)
    units = len(chinese_chars) + len(latin_words)
    return max(1, round(units / 500))


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def is_table_start(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and "|" in lines[index] and TABLE_SEPARATOR_RE.match(lines[index + 1]) is not None


def render_table(table_lines: list[str]) -> str:
    rows = [split_table_row(line) for line in table_lines]
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = rows[2:]
    header_cells = "".join(
        '<th style="padding:13px 14px;background:#fdf6ec;color:#1a1a1a;'
        'font-size:14px;line-height:1.5;text-align:left;font-weight:800;letter-spacing:0.3px;'
        'border-bottom:2px solid #c2410c;">'
        + markdown_inline_to_html(cell)
        + "</th>"
        for cell in header
    )
    body_rows = []
    for row_index, row in enumerate(body):
        is_last = row_index == len(body) - 1
        stripe = "#ffffff" if row_index % 2 == 0 else "#fbf6ec"
        border = "" if is_last else "border-bottom:1px solid #f0e6d2;"
        cells = "".join(
            f'<td style="padding:12px 14px;color:#2b2b2b;background:{stripe};'
            f'font-size:14.5px;line-height:1.75;vertical-align:top;{border}">'
            + markdown_inline_to_html(cell)
            + "</td>"
            for cell in row
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<section style="width:100%;overflow:auto;margin:28px 0;border-radius:10px;'
        'border:1px solid #ece4d6;box-sizing:border-box;background:#ffffff;">'
        '<table style="width:100%;border-collapse:collapse;background:#ffffff;">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></section>"
    )


def render_divider() -> str:
    return (
        '<p style="margin:48px 0 44px;text-align:center;line-height:1;">'
        '<span style="display:inline-block;color:#c2a874;font-size:10px;'
        'letter-spacing:14px;padding-left:14px;">● ● ●</span>'
        "</p>"
    )


def render_callout(text: str) -> str:
    marker, label, body = parse_callout(text)
    _, background, border, color = CALLOUT_MARKERS.get(marker, ("提示", "#fdf6ec", "#c2410c", "#7c2d12"))
    return (
        f'<section style="margin:30px 0;padding:20px 22px 18px;background:{background};'
        f'border-left:3px solid {border};border-radius:2px 10px 10px 2px;color:{color};'
        'font-size:15.5px;line-height:1.95;width:100%;box-sizing:border-box;">'
        f'<p style="margin:0 0 8px;color:{border};font-size:12px;font-weight:800;'
        'letter-spacing:2px;text-transform:uppercase;line-height:1.4;">'
        f'<span style="margin-right:6px;">{html.escape(marker)}</span>'
        f'{html.escape(label)}'
        '</p>'
        f'<p style="margin:0;color:{color};font-size:15.5px;line-height:1.95;font-weight:400;">'
        + markdown_inline_to_html(body)
        + '</p>'
        + "</section>"
    )


def render_image_caption(text: str) -> str:
    """Render '*▼ caption*' style paragraphs as a clean italic editorial caption.

    These appear right under images and describe what the reader is looking at.
    Top WeChat accounts use a small centered italic caption rather than a pill,
    because the pill looks like a tag instead of a caption.
    """
    match = IMAGE_CAPTION_RE.match(text)
    arrow = match.group(1) if match else ""
    body = match.group(2) if match else text
    inner = markdown_inline_to_html(body)
    return (
        '<p style="margin:-6px 0 28px;text-align:center;line-height:1.65;color:#8a8a8a;'
        'font-size:13px;letter-spacing:0.4px;">'
        f'<span style="margin-right:4px;color:#c2410c;">{html.escape(arrow)}</span>'
        f'<span style="font-style:normal;">{inner}</span>'
        "</p>"
    )


def is_generated_table_image(src: str) -> bool:
    normalized = src.replace("\\", "/")
    return (
        normalized.startswith("assets/tables/")
        or normalized.startswith("../assets/tables/")
        or "/assets/tables/" in normalized
        or "/tables/table_" in normalized
    )


def render_list(items: list[str], ordered: bool, start: int | None = None) -> str:
    if ordered:
        first_number = start or 1
        rendered = []
        for offset, item in enumerate(items):
            number = first_number + offset
            number_label = f"{number:02d}" if number < 100 else str(number)
            rendered.append(
                '<p style="font-size:16px;line-height:1.95;margin:0 0 12px;color:#2b2b2b;'
                'padding-left:0;box-sizing:border-box;">'
                f'<span style="display:inline-block;min-width:34px;color:#c2410c;'
                f'font-weight:800;font-size:15px;letter-spacing:0.5px;'
                f'font-family:Menlo,Consolas,-apple-system,sans-serif;">{number_label}.</span>'
                + markdown_inline_to_html(item.strip())
                + "</p>"
            )
        return "".join(rendered)

    rendered_items = "".join(
        '<p style="font-size:16px;line-height:1.95;margin:0 0 10px;color:#2b2b2b;'
        'padding-left:4px;box-sizing:border-box;">'
        '<span style="display:inline-block;width:5px;height:5px;background:#c2410c;'
        'border-radius:50%;vertical-align:3px;margin-right:12px;"></span>'
        + markdown_inline_to_html(item.strip())
        + "</p>"
        for item in items
    )
    return rendered_items


def render_code_block(code: str, language: str) -> str:
    safe_code = render_code_with_placeholder_badges(code)
    language_label = ""
    safe_language = html.escape(language.strip()) if language else ""
    if safe_language:
        language_label = (
            '<p style="margin:0 0 8px;color:#9a3412;font-size:11px;font-weight:800;'
            'letter-spacing:2px;text-transform:uppercase;line-height:1;'
            'font-family:Menlo,Consolas,monospace;">'
            f'{safe_language}'
            '</p>'
        )
    return (
        '<section style="margin:26px 0;padding:16px 18px 14px;background:#faf6ed;'
        'border:1px solid #ece4d6;border-left:3px solid #c2410c;'
        'border-radius:2px 8px 8px 2px;color:#1a1a1a;font-size:13px;line-height:1.75;'
        'width:100%;box-sizing:border-box;">'
        + language_label
        + '<pre style="margin:0;padding:0;background:transparent;border:0;color:#1a1a1a;'
        'font-size:13px;line-height:1.75;font-family:Menlo,Consolas,monospace;'
        'white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;">'
        '<code style="display:block;font-family:Menlo,Consolas,monospace;color:#1a1a1a;'
        'background:transparent;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;">'
        + safe_code
        + "</code></pre></section>"
    )


def render_code_with_placeholder_badges(code: str) -> str:
    chunks: list[str] = []
    last = 0

    def replace(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        label = CODE_PLACEHOLDERS.get(value, value)
        return (
            f'<span data-placeholder="code" style="{CODE_PLACEHOLDER_STYLE}">'
            + html.escape(f"【{label}】")
            + "</span>"
        )

    for match in re.finditer(r"【([^】]+)】", code):
        chunks.append(html.escape(code[last : match.start()]))
        chunks.append(replace(match))
        last = match.end()
    chunks.append(html.escape(code[last:]))
    return "".join(chunks)


def normalize_code_placeholder_text(code: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        return f"【{CODE_PLACEHOLDERS.get(value, value)}】"

    return re.sub(r"【([^】]+)】", replace, code)


def render_platform_code_block(code: str, language: str) -> str:
    safe_code = html.escape(normalize_code_placeholder_text(code))
    safe_language = html.escape(language.strip())
    label = f'<div style="margin:0 0 6px;color:#64748b;font-size:12px;">{safe_language}</div>' if safe_language else ""
    return (
        '<pre style="margin:20px 0;padding:13px 14px;background:#f8fafc;border:1px solid #cbd5e1;'
        'border-radius:6px;color:#0f172a;font-size:13px;line-height:1.75;'
        'font-family:Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word;'
        'overflow-wrap:anywhere;box-sizing:border-box;">'
        + label
        + '<code style="font-family:Menlo,Consolas,monospace;white-space:pre-wrap;background:transparent;color:#0f172a;">'
        + safe_code
        + "</code></pre>"
    )


def image_label(alt_text: str, index: int) -> str:
    label = strip_inline_markdown(alt_text).strip()
    if not label or label.lower() == "image":
        return f"图片 {index}"
    return label


def sniff_image_mime(data: bytes) -> str | None:
    if len(data) >= 12:
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[:4] == b"<svg" or data[:5] == b"<?xml":
            return "image/svg+xml"
    return None


def image_src_for_mode(src: str, image_mode: str, asset_base_dir: Path | None = None) -> str:
    if image_mode != "data" or REMOTE_RE.match(src) or asset_base_dir is None:
        return src
    path = (asset_base_dir / src).resolve()
    if not path.exists() or not path.is_file():
        return src
    raw = path.read_bytes()
    # Notion exports often drop file extensions (e.g. image_*.bin), so we sniff
    # the magic bytes first and only fall back to the extension-based guess.
    mime_type = sniff_image_mime(raw) or mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def render_image_block(
    alt_text: str,
    src: str,
    index: int,
    image_mode: str,
    asset_base_dir: Path | None = None,
) -> str:
    label = image_label(alt_text, index)
    safe_label = html.escape(label)
    safe_src = html.escape(image_src_for_mode(src, image_mode, asset_base_dir))
    is_table_image = is_generated_table_image(src)
    if image_mode == "placeholder":
        return (
            '<p style="margin:24px 0;padding:12px 14px;background:#f8fafc;border:1px dashed #cbd5e1;'
            'border-radius:8px;color:#475569;font-size:14px;line-height:1.75;width:100%;box-sizing:border-box;">'
            f'<strong style="color:#334155;font-weight:700;">图片占位 {index}：{safe_label}</strong><br>'
            f'<span style="font-size:12px;color:#64748b;">发布时上传并替换：{safe_src}</span>'
            "</p>"
        )
    caption = ""
    if alt_text.strip() and alt_text.strip().lower() != "image" and not is_table_image:
        caption = (
            '<p style="margin:-4px 0 28px;text-align:center;line-height:1.65;color:#8a8a8a;'
            'font-size:13px;letter-spacing:0.4px;">'
            '<span style="color:#c2410c;margin-right:4px;">▼</span>'
            + safe_label
            + "</p>"
        )
    image_style = (
        "display:block;max-width:100%;height:auto;border-radius:6px;margin:0 auto;"
        "border:1px solid #ece4d6;box-shadow:0 6px 18px rgba(120,80,30,0.06);"
    )
    if not is_table_image:
        image_style = (
            "display:block;max-width:100%;height:auto;border-radius:8px;margin:0 auto;"
            "box-shadow:0 8px 28px rgba(120,80,30,0.10);"
        )
    return (
        '<p style="margin:30px 0 12px;text-align:center;">'
        f'<img src="{safe_src}" alt="{safe_label}" style="{image_style}" />'
        "</p>"
        + caption
    )


def extract_image_manifest(markdown: str) -> list[dict[str, object]]:
    manifest: list[dict[str, object]] = []
    for index, match in enumerate(IMAGE_RE.finditer(markdown), start=1):
        alt_text = match.group(1).strip()
        src = clean_image_target(match.group(2))
        manifest.append({"index": index, "label": image_label(alt_text, index), "src": src})
    return manifest


def render_image_manifest(title: str, manifest: list[dict[str, object]]) -> str:
    lines = [f"# {title} 图片上传清单", ""]
    if not manifest:
        lines.append("本文没有本地图片。")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "非知乎平台的主 HTML 会尽量内嵌本地图片。",
            "知乎通过 md2zhihu 生成 `platforms/zhihu.md`，图片由 Git 图床托管为 HTTPS 链接。如果未配置 `--zhihu-asset-repo` 或未安装 md2zhihu，`zhihu.md` 会使用本地 `../assets/` 链接，请按下列顺序从 `assets/` 手工补图。",
            "",
        ]
    )
    for item in manifest:
        lines.append(f"{item['index']}. {item['label']}")
        lines.append(f"   - 文件：`{item['src']}`")
    return "\n".join(lines) + "\n"


def render_blocks(
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    quote_lines: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    in_code = False
    code_language = ""
    # `pending_lead_in` is True for the very first paragraph of the article and
    # again right after every H2, so each section opens with a slightly larger,
    # deeper-colored lead paragraph (editorial column rhythm). It is consumed
    # by the next non-callout, non-caption paragraph and then auto-resets.
    pending_lead_in = True
    ordered_number = 0
    image_index = 0

    def flush_paragraph() -> None:
        nonlocal pending_lead_in, ordered_number
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_callout(text))
        elif IMAGE_CAPTION_RE.match(text):
            html_lines.append(render_image_caption(text))
        else:
            style = (
                "font-size:17px;line-height:2.05;margin:0 0 26px;color:#1a1a1a;font-weight:400;letter-spacing:0.3px;"
                if pending_lead_in
                else "font-size:16px;line-height:2;margin:0 0 22px;color:#2b2b2b;letter-spacing:0.2px;"
            )
            html_lines.append(f'<p style="{style}">' + markdown_inline_to_html(text) + "</p>")
            # Only true text paragraphs consume the lead-in flag; callouts and
            # image captions do not, so the next real paragraph still gets the
            # bigger opener treatment.
            pending_lead_in = False
        ordered_number = 0
        paragraph.clear()

    def flush_quote() -> None:
        nonlocal ordered_number
        if not quote_lines:
            return
        text = " ".join(quote_lines).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_callout(text))
            ordered_number = 0
            quote_lines.clear()
            return
        html_lines.append(
            '<section style="margin:30px 0;padding:18px 24px 14px;background:#fdf6ec;'
            'border-left:3px solid #c2410c;border-radius:2px 10px 10px 2px;'
            'width:100%;box-sizing:border-box;position:relative;">'
            '<p style="margin:0 0 6px;color:#c2410c;font-size:22px;line-height:1;'
            "font-family:Georgia,serif;font-weight:700;\">&ldquo;</p>"
            '<p style="margin:0;color:#3c2a14;font-size:15.5px;line-height:1.95;'
            'font-style:italic;letter-spacing:0.3px;">'
            + markdown_inline_to_html(text)
            + "</p>"
            # Editorial closing glyph: a small terracotta &rdquo; aligned to
            # the right tail so the quote card visually "closes" instead of
            # trailing off into whitespace.
            '<p style="margin:4px 0 0;color:#c2410c;font-size:20px;line-height:1;'
            "font-family:Georgia,serif;font-weight:700;text-align:right;\">&rdquo;</p>"
            "</section>"
        )
        ordered_number = 0
        quote_lines.clear()

    def flush_list() -> None:
        nonlocal ordered_number
        if not list_items:
            return
        start = ordered_number + 1 if list_ordered else None
        html_lines.append(render_list(list_items, list_ordered, start))
        if list_ordered:
            ordered_number += len(list_items)
        list_items.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                html_lines.append(render_code_block("\n".join(code_lines), code_language))
                code_lines.clear()
                in_code = False
                code_language = ""
            else:
                flush_list()
                flush_paragraph()
                flush_quote()
                in_code = True
                code_language = line[3:].strip()
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not line.strip():
            flush_list()
            flush_paragraph()
            flush_quote()
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_list()
            flush_paragraph()
            flush_quote()
            level = len(heading.group(1))
            text = markdown_inline_to_html(heading.group(2).strip())
            if level == 2:
                html_lines.append(
                    '<h2 style="font-size:22px;line-height:1.55;margin:56px 0 24px;color:#1a1a1a;'
                    'font-weight:800;padding:0 0 14px;border-bottom:1px solid #ece4d6;'
                    'width:100%;box-sizing:border-box;letter-spacing:0.5px;background:transparent;">'
                    '<span style="display:inline-block;width:8px;height:20px;background:#c2410c;'
                    'margin-right:12px;vertical-align:-3px;border-radius:1px;"></span>'
                    + text
                    + "</h2>"
                )
                ordered_number = 0
                # Each H2 opens a new section; the very next text paragraph
                # should be styled as the section lead-in (bigger, deeper
                # color) to match the magazine column rhythm.
                pending_lead_in = True
            else:
                html_lines.append(
                    '<h3 style="font-size:18px;line-height:1.6;margin:40px 0 18px;color:#1a1a1a;'
                    'font-weight:800;padding:0;background:transparent;'
                    'width:100%;box-sizing:border-box;letter-spacing:0.3px;">'
                    '<span style="color:#c2410c;font-weight:900;margin-right:8px;'
                    'font-size:18px;">▍</span>'
                    '<span style="border-bottom:2px solid #fde68a;padding-bottom:4px;">'
                    + text
                    + "</span></h3>"
                )
                ordered_number = 0
            index += 1
            continue

        if HR_RE.match(line):
            flush_list()
            flush_paragraph()
            flush_quote()
            html_lines.append(render_divider())
            ordered_number = 0
            index += 1
            continue

        if is_table_start(lines, index):
            flush_list()
            flush_paragraph()
            flush_quote()
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            html_lines.append(render_table(table_lines))
            ordered_number = 0
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            image_index += 1
            flush_list()
            flush_paragraph()
            flush_quote()
            alt_text = image.group(1).strip()
            src = clean_image_target(image.group(2))
            html_lines.append(render_image_block(alt_text, src, image_index, image_mode, asset_base_dir))
            index += 1
            continue

        if line.lstrip().startswith(">"):
            flush_list()
            flush_paragraph()
            quote_lines.append(line.lstrip()[1:].strip())
            index += 1
            continue

        unordered = UNORDERED_LIST_RE.match(line)
        ordered = ORDERED_LIST_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            is_ordered = ordered is not None
            content = (ordered or unordered).group(1).strip()
            if list_items and list_ordered != is_ordered:
                flush_list()
            list_ordered = is_ordered
            list_items.append(content)
            index += 1
            continue

        flush_list()
        paragraph.append(line)
        index += 1

    flush_list()
    flush_paragraph()
    flush_quote()
    if in_code and code_lines:
        html_lines.append(render_code_block("\n".join(code_lines), code_language))
    return "\n".join(html_lines)


def render_platform_table(table_lines: list[str]) -> str:
    rows = [split_table_row(line) for line in table_lines]
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = rows[2:]
    header_cells = "".join(
        '<th style="padding:8px 10px;border:1px solid #d1d5db;text-align:left;">'
        + markdown_inline_to_editor_html(cell)
        + "</th>"
        for cell in header
    )
    body_rows = []
    for row in body:
        cells = "".join(
            '<td style="padding:8px 10px;border:1px solid #d1d5db;vertical-align:top;">'
            + markdown_inline_to_editor_html(cell)
            + "</td>"
            for cell in row
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;margin:18px 0;">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def render_platform_list(items: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    rendered_items = "".join("<li>" + markdown_inline_to_editor_html(item.strip()) + "</li>" for item in items)
    return f'<{tag} style="margin:0 0 18px 1.2em;padding:0;line-height:1.85;">{rendered_items}</{tag}>'


def render_platform_image_block(
    alt_text: str,
    src: str,
    index: int,
    platform: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    profile = PLATFORM_PROFILES[platform]
    label = html.escape(image_label(alt_text, index))
    safe_src = html.escape(image_src_for_mode(src, image_mode, asset_base_dir))
    if image_mode != "placeholder":
        caption = ""
        if alt_text.strip() and alt_text.strip().lower() != "image":
            caption = (
                '<p style="margin:-12px 0 20px;text-align:center;color:#64748b;font-size:12px;line-height:1.6;">'
                + label
                + "</p>"
            )
        return (
            '<p style="margin:22px 0;text-align:center;">'
            f'<img src="{safe_src}" alt="{label}" style="display:block;max-width:100%;height:auto;margin:0 auto;border-radius:6px;" />'
            "</p>"
            + caption
        )
    return (
        '<p style="margin:22px 0;padding:10px 12px;border:1px dashed #cbd5e1;background:#f8fafc;'
        'border-radius:6px;color:#475569;line-height:1.7;">'
        f'<strong>图片占位 {index}：{label}</strong><br>'
        f'<span>发布到{html.escape(str(profile["label"]))}时上传并替换：{html.escape(src)}</span>'
        "</p>"
    )


def render_platform_blocks(
    markdown: str,
    platform: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    quote_lines: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    in_code = False
    code_language = ""
    image_index = 0

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(
                '<blockquote style="margin:18px 0;padding:12px 14px;border-left:4px solid #f59e0b;'
                'background:#fff7ed;color:#7c2d12;line-height:1.85;">'
                + markdown_inline_to_editor_html(text)
                + "</blockquote>"
            )
        elif IMAGE_CAPTION_RE.match(text):
            html_lines.append(render_editor_image_caption(text))
        else:
            html_lines.append(
                '<p style="margin:0 0 16px;line-height:1.85;color:#1f2937;">'
                + markdown_inline_to_editor_html(text)
                + "</p>"
            )
        paragraph.clear()

    def flush_quote() -> None:
        if not quote_lines:
            return
        text = " ".join(quote_lines).strip()
        html_lines.append(
            '<blockquote style="margin:18px 0;padding:12px 14px;border-left:4px solid #64748b;'
            'background:#f8fafc;color:#334155;line-height:1.85;">'
            + markdown_inline_to_editor_html(text)
            + "</blockquote>"
        )
        quote_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        html_lines.append(render_platform_list(list_items, list_ordered))
        list_items.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                html_lines.append(render_platform_code_block("\n".join(code_lines), code_language))
                code_lines.clear()
                in_code = False
                code_language = ""
            else:
                flush_list()
                flush_paragraph()
                flush_quote()
                in_code = True
                code_language = line[3:].strip()
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not line.strip():
            flush_list()
            flush_paragraph()
            flush_quote()
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_list()
            flush_paragraph()
            flush_quote()
            level = len(heading.group(1))
            text = markdown_inline_to_editor_html(heading.group(2).strip())
            tag = "h2" if level <= 2 else "h3"
            style = (
                "font-size:22px;line-height:1.45;margin:30px 0 14px;font-weight:700;color:#111827;"
                if tag == "h2"
                else "font-size:18px;line-height:1.55;margin:24px 0 10px;font-weight:700;color:#111827;"
            )
            html_lines.append(f'<{tag} style="{style}">{text}</{tag}>')
            index += 1
            continue

        if HR_RE.match(line):
            flush_list()
            flush_paragraph()
            flush_quote()
            html_lines.append('<hr style="border:0;border-top:1px solid #e5e7eb;margin:28px 0;">')
            index += 1
            continue

        if is_table_start(lines, index):
            flush_list()
            flush_paragraph()
            flush_quote()
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            html_lines.append(render_platform_table(table_lines))
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            image_index += 1
            flush_list()
            flush_paragraph()
            flush_quote()
            html_lines.append(
                render_platform_image_block(
                    image.group(1).strip(),
                    clean_image_target(image.group(2)),
                    image_index,
                    platform,
                    image_mode=image_mode,
                    asset_base_dir=asset_base_dir,
                )
            )
            index += 1
            continue

        if line.lstrip().startswith(">"):
            flush_list()
            flush_paragraph()
            quote_lines.append(line.lstrip()[1:].strip())
            index += 1
            continue

        unordered = UNORDERED_LIST_RE.match(line)
        ordered = ORDERED_LIST_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            is_ordered = ordered is not None
            content = (ordered or unordered).group(1).strip()
            if list_items and list_ordered != is_ordered:
                flush_list()
            list_ordered = is_ordered
            list_items.append(content)
            index += 1
            continue

        flush_list()
        paragraph.append(line)
        index += 1

    flush_list()
    flush_paragraph()
    flush_quote()
    if in_code and code_lines:
        html_lines.append(render_platform_code_block("\n".join(code_lines), code_language))
    return "\n".join(html_lines)


def render_toutiao_table(table_lines: list[str]) -> str:
    return render_zsxq_table(table_lines)


def render_toutiao_image_block(
    alt_text: str,
    src: str,
    index: int,
    image_mode: str,
    asset_base_dir: Path | None = None,
) -> str:
    label = html.escape(image_label(alt_text, index))
    safe_src = html.escape(image_src_for_mode(src, image_mode, asset_base_dir))
    if image_mode == "placeholder":
        return f"<p><strong>图片占位 {index}：</strong>{label}<br>{html.escape(src)}</p>"
    return f'<p><img src="{safe_src}" alt="{label}"></p>'


def render_toutiao_code_block(code: str) -> str:
    return "<pre><code>" + html.escape(normalize_code_placeholder_text(code)) + "</code></pre>"


def render_toutiao_ordered_list(items: list[str], start: int) -> str:
    paragraphs = []
    for offset, item in enumerate(items):
        number = start + offset
        paragraphs.append(
            f"<p><strong>{number}.</strong>&nbsp;"
            + markdown_inline_to_editor_html(item.strip())
            + "</p>"
        )
    return "\n".join(paragraphs)


def render_toutiao_callout(text: str) -> str:
    marker, label, body = parse_callout(text)
    return (
        "<blockquote><p>"
        f"<strong>{html.escape((marker + ' ' + label + '：').strip())}</strong>"
        f"{markdown_inline_to_editor_html(body)}"
        "</p></blockquote>"
    )


def should_promote_toutiao_quote(text: str) -> bool:
    plain = strip_inline_markdown(text)
    if plain.startswith(("先说结论：", "整个流程：", "适合你：", "先看重点：")):
        return True
    keyword_groups = (
        ("不支持直接导入", "需要手动新建"),
        ("复制保存到本地", "不要发到任何公开平台"),
        ("不用时停止实例", "别留闲置资源"),
        ("不要碰 GPU", "负载均衡"),
        ("Standard persistent disk", "Standard"),
    )
    return any(all(keyword in plain for keyword in keywords) for keywords in keyword_groups)


def render_toutiao_quote_paragraph(text: str) -> str:
    return "<blockquote><p>" + markdown_inline_to_editor_html(text) + "</p></blockquote>"


def toutiao_block_type(block: str) -> str:
    if block.startswith("<h2>"):
        return "h2"
    if block.startswith("<h3>"):
        return "h3"
    if block.startswith("<blockquote>"):
        return "quote"
    if block.startswith("<pre>"):
        return "code"
    if block.startswith("<ul>"):
        return "list"
    if re.match(r"^<p><strong>\d+\.</strong>", block):
        return "list"
    if '<img src="' in block:
        return "image"
    return "paragraph"


def apply_toutiao_spacing(blocks: list[str]) -> list[str]:
    return blocks


def render_toutiao_blocks(
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    quote_lines: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    in_code = False
    image_index = 0
    ordered_number = 0

    def flush_paragraph() -> None:
        nonlocal ordered_number
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_toutiao_callout(text))
        elif IMAGE_CAPTION_RE.match(text):
            html_lines.append(render_editor_image_caption(text))
        elif should_promote_toutiao_quote(text):
            html_lines.append(render_toutiao_quote_paragraph(text))
        else:
            for paragraph_text in split_zsxq_paragraph(text, max_chars=80):
                html_lines.append("<p>" + markdown_inline_to_editor_html(paragraph_text) + "</p>")
        ordered_number = 0
        paragraph.clear()

    def flush_quote() -> None:
        nonlocal ordered_number
        if not quote_lines:
            return
        text = " ".join(item.strip() for item in quote_lines).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_toutiao_callout(text))
        else:
            html_lines.append(render_toutiao_quote_paragraph(text))
        ordered_number = 0
        quote_lines.clear()

    def flush_list() -> None:
        nonlocal ordered_number
        if not list_items:
            return
        if list_ordered:
            start = ordered_number + 1
            html_lines.append(render_toutiao_ordered_list(list_items, start))
            ordered_number += len(list_items)
        else:
            items = "".join("<li>" + markdown_inline_to_editor_html(item.strip()) + "</li>" for item in list_items)
            html_lines.append(f"<ul>{items}</ul>")
            ordered_number = 0
        list_items.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                html_lines.append(render_toutiao_code_block("\n".join(code_lines)))
                code_lines.clear()
                in_code = False
            else:
                flush_list()
                flush_paragraph()
                flush_quote()
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not line.strip():
            flush_list()
            flush_paragraph()
            flush_quote()
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_list()
            flush_paragraph()
            flush_quote()
            level = len(heading.group(1))
            text = markdown_inline_to_editor_html(heading.group(2).strip())
            tag = "h2" if level <= 2 else "h3"
            html_lines.append(f"<{tag}>{text}</{tag}>")
            ordered_number = 0
            index += 1
            continue

        if HR_RE.match(line):
            flush_list()
            flush_paragraph()
            flush_quote()
            ordered_number = 0
            index += 1
            continue

        if is_table_start(lines, index):
            flush_list()
            flush_paragraph()
            flush_quote()
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            html_lines.append(render_toutiao_table(table_lines))
            ordered_number = 0
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            image_index += 1
            flush_list()
            flush_paragraph()
            flush_quote()
            html_lines.append(
                render_toutiao_image_block(
                    image.group(1).strip(),
                    clean_image_target(image.group(2)),
                    image_index,
                    image_mode=image_mode,
                    asset_base_dir=asset_base_dir,
                )
            )
            index += 1
            continue

        if line.lstrip().startswith(">"):
            flush_list()
            flush_paragraph()
            quote_lines.append(line.lstrip()[1:].strip())
            index += 1
            continue

        unordered = UNORDERED_LIST_RE.match(line)
        ordered = ORDERED_LIST_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            is_ordered = ordered is not None
            content = (ordered or unordered).group(1).strip()
            if list_items and list_ordered != is_ordered:
                flush_list()
            list_ordered = is_ordered
            list_items.append(content)
            index += 1
            continue

        flush_list()
        paragraph.append(line)
        index += 1

    flush_list()
    flush_paragraph()
    flush_quote()
    if in_code and code_lines:
        html_lines.append(render_toutiao_code_block("\n".join(code_lines)))
    return "\n".join(apply_toutiao_spacing(html_lines))


PLATFORM_TITLE_SUFFIX = {
    "zhihu": "知乎正文粘贴版",
    "toutiao": "今日头条正文粘贴版",
    "zsxq": "知识星球长文粘贴版",
    "smzdm": "什么值得买正文粘贴版",
}


def render_magazine_platform_html(
    platform: str,
    title: str,
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    """Render a non-WeChat platform's article body using the same magazine
    layout as WeChat.

    All four richtext platforms (Zhihu, Toutiao, Zsxq, SMZDM) accept inline
    CSS pasted from a browser preview. By sharing the WeChat magazine
    renderer (`render_blocks`) every callout / emoji badge / code block /
    table / list improvement automatically benefits every platform — one
    place to fix, one regression test surface.

    The only per-platform differences are:
    - the `<title>` suffix shown in the browser tab,
    - the image mode (Zhihu uses `placeholder`/HTTPS, others use `data`).
    """
    body = render_blocks(markdown, image_mode=image_mode, asset_base_dir=asset_base_dir)
    safe_title = html.escape(title)
    suffix = PLATFORM_TITLE_SUFFIX.get(platform, str(PLATFORM_PROFILES[platform]["label"]))
    safe_suffix = html.escape(suffix)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - {safe_suffix}</title>
</head>
<body style="box-sizing:border-box;margin:0;background:#f7f3ec;padding:18px 0;overflow-x:hidden;">
  <article style="width:calc(100% - 40px);max-width:720px;box-sizing:border-box;margin:0 auto;background:#ffffff;padding:30px 22px 36px;color:#222222;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;">
{body}
  </article>
</body>
</html>
"""


def render_toutiao_html(
    title: str,
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    return render_magazine_platform_html("toutiao", title, markdown, image_mode=image_mode, asset_base_dir=asset_base_dir)


def render_platform_html(
    platform: str,
    title: str,
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    if platform == "zsxq":
        return render_zsxq_html(title, markdown, image_mode=image_mode, asset_base_dir=asset_base_dir)

    # Other richtext HTML targets keep the shared magazine renderer. Zsxq is
    # intentionally separate because its editor pastes WeChat-style wrappers
    # poorly and works better with low-style native tags.
    return render_magazine_platform_html(
        platform,
        title,
        markdown,
        image_mode=image_mode,
        asset_base_dir=asset_base_dir,
    )


def render_zsxq_table(table_lines: list[str]) -> str:
    rows = [split_table_row(line) for line in table_lines]
    if len(rows) < 2:
        return ""
    header = [strip_inline_markdown(cell) for cell in rows[0]]
    body = rows[2:]
    items = []
    compact_budget_table = (
        len(header) == 2
        and header[0] in {"阈值", "预算比例", "比例"}
        and header[1] in {"动作", "提醒", "提醒动作"}
    )
    for row in body:
        label = markdown_inline_to_editor_html(row[0]) if row else "项目"
        label_is_bold = label.startswith("<strong>") and label.endswith("</strong>")
        label_html = label if label_is_bold else f"<strong>{label}</strong>"
        if compact_budget_table and len(row) >= 2:
            items.append(f"<li>{label_html}：{markdown_inline_to_editor_html(row[1])}</li>")
            continue
        details = []
        for cell_index, cell in enumerate(row[1:], start=1):
            key = header[cell_index] if cell_index < len(header) else f"字段 {cell_index + 1}"
            details.append(
                "<strong>"
                + html.escape(key)
                + "：</strong>"
                + markdown_inline_to_editor_html(cell)
            )
        suffix = "<br>".join(details)
        items.append(f"<li>{label_html}<br>{suffix}</li>" if suffix else f"<li>{label_html}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def render_zsxq_image_block(
    alt_text: str,
    src: str,
    index: int,
    image_mode: str,
    asset_base_dir: Path | None = None,
) -> str:
    label = html.escape(image_label(alt_text, index))
    safe_src = html.escape(image_src_for_mode(src, image_mode, asset_base_dir))
    if image_mode == "placeholder":
        return f'<p style="{ZSXQ_PARAGRAPH_STYLE}"><strong>图片占位：</strong>{label}<br>{html.escape(src)}</p>'
    caption = ""
    if alt_text.strip() and alt_text.strip().lower() != "image" and not is_generated_table_image(src):
        caption = f'<p style="{ZSXQ_CAPTION_STYLE}"><em>▼ {label}</em></p>'
    return f'<p style="margin:1.15em 0 0;text-align:center;"><img src="{safe_src}" alt="{label}" style="{ZSXQ_IMAGE_STYLE}"></p>' + caption


def render_zsxq_code_block(code: str) -> str:
    return (
        '<pre style="margin:1.15em 0;padding:12px 14px;background:#f8fafc;border:1px solid #e5e7eb;'
        'border-radius:6px;white-space:pre-wrap;word-break:break-word;line-height:1.7;font-size:13px;">'
        "<code>"
        + html.escape(normalize_code_placeholder_text(code))
        + "</code></pre>"
    )


def render_zsxq_ordered_list(items: list[str], start: int) -> str:
    paragraphs = []
    for offset, item in enumerate(items):
        number = start + offset
        paragraphs.append(
            f'<p style="{ZSXQ_PARAGRAPH_STYLE}"><strong>{number}.</strong>&nbsp;'
            + markdown_inline_to_editor_html(item.strip())
            + "</p>"
        )
    return "\n".join(paragraphs)


def split_zsxq_paragraph(text: str, max_chars: int = 86) -> list[str]:
    if len(strip_inline_markdown(text)) <= max_chars:
        return [text]
    segments = re.split(r"(?<=[。！？；])\s*", text)
    chunks: list[str] = []
    current = ""
    for segment in segments:
        if not segment:
            continue
        candidate = current + segment if current else segment
        if current and len(strip_inline_markdown(candidate)) > max_chars and not has_unclosed_inline_markup(current):
            chunks.append(current)
            current = segment
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def has_unclosed_inline_markup(text: str) -> bool:
    # Sentence splitting must not leave half of **bold**, __bold__, or `code`
    # in one paragraph and the closing marker in the next.
    value = re.sub(r"\\.", "", text)
    return value.count("**") % 2 == 1 or value.count("__") % 2 == 1 or value.count("`") % 2 == 1


def render_zsxq_callout(text: str) -> str:
    marker, label, body = parse_callout(text)
    return (
        f'<p style="{ZSXQ_QUOTE_STYLE}">'
        f"<strong>{ZSXQ_QUOTE_MARKER}{html.escape((marker + ' ' + label + '：').strip())}</strong>"
        f"{markdown_inline_to_editor_html(body)}"
        "</p>"
    )


def should_promote_zsxq_quote(text: str) -> bool:
    plain = strip_inline_markdown(text)
    if plain.startswith("整个流程："):
        return True
    keyword_groups = (
        ("不支持直接导入", "需要手动新建"),
        ("复制保存到本地", "不要发到任何公开平台"),
        ("不用时停止实例", "别留闲置资源"),
    )
    return any(all(keyword in plain for keyword in keywords) for keywords in keyword_groups)


def render_zsxq_quote_paragraph(text: str) -> str:
    return f'<p style="{ZSXQ_QUOTE_STYLE}"><strong>{ZSXQ_QUOTE_MARKER}</strong>&nbsp;' + markdown_inline_to_editor_html(text) + "</p>"


def render_zsxq_blocks(
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    quote_lines: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    in_code = False
    image_index = 0
    ordered_number = 0

    def flush_paragraph() -> None:
        nonlocal ordered_number
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_zsxq_callout(text))
        elif IMAGE_CAPTION_RE.match(text):
            html_lines.append(render_editor_image_caption(text))
        elif should_promote_zsxq_quote(text):
            html_lines.append(render_zsxq_quote_paragraph(text))
        else:
            for paragraph_text in split_zsxq_paragraph(text):
                html_lines.append(f'<p style="{ZSXQ_PARAGRAPH_STYLE}">' + markdown_inline_to_editor_html(paragraph_text) + "</p>")
        ordered_number = 0
        paragraph.clear()

    def flush_quote() -> None:
        nonlocal ordered_number
        if not quote_lines:
            return
        text = " ".join(item.strip() for item in quote_lines).strip()
        if any(text.startswith(marker) for marker in CALLOUT_MARKERS):
            html_lines.append(render_zsxq_callout(text))
        else:
            html_lines.append(render_zsxq_quote_paragraph(text))
        ordered_number = 0
        quote_lines.clear()

    def flush_list() -> None:
        nonlocal ordered_number
        if not list_items:
            return
        if list_ordered:
            start = ordered_number + 1
            html_lines.append(render_zsxq_ordered_list(list_items, start))
            ordered_number += len(list_items)
        else:
            items = "".join("<li>" + markdown_inline_to_editor_html(item.strip()) + "</li>" for item in list_items)
            html_lines.append(f'<ul style="margin:0 0 1.05em 1.2em;padding:0;line-height:1.85;font-size:16px;color:#1f2937;">{items}</ul>')
            ordered_number = 0
        list_items.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                html_lines.append(render_zsxq_code_block("\n".join(code_lines)))
                code_lines.clear()
                in_code = False
            else:
                flush_list()
                flush_paragraph()
                flush_quote()
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not line.strip():
            flush_list()
            flush_paragraph()
            flush_quote()
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_list()
            flush_paragraph()
            flush_quote()
            level = len(heading.group(1))
            text = markdown_inline_to_editor_html(heading.group(2).strip())
            tag = "h2" if level <= 2 else "h3"
            html_lines.append(f'<{tag} style="{ZSXQ_HEADING_STYLE}">{text}</{tag}>')
            ordered_number = 0
            index += 1
            continue

        if HR_RE.match(line):
            flush_list()
            flush_paragraph()
            flush_quote()
            ordered_number = 0
            index += 1
            continue

        if is_table_start(lines, index):
            flush_list()
            flush_paragraph()
            flush_quote()
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            html_lines.append(render_zsxq_table(table_lines))
            ordered_number = 0
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            image_index += 1
            flush_list()
            flush_paragraph()
            flush_quote()
            html_lines.append(
                render_zsxq_image_block(
                    image.group(1).strip(),
                    clean_image_target(image.group(2)),
                    image_index,
                    image_mode=image_mode,
                    asset_base_dir=asset_base_dir,
                )
            )
            index += 1
            continue

        if line.lstrip().startswith(">"):
            flush_list()
            flush_paragraph()
            quote_lines.append(line.lstrip()[1:].strip())
            index += 1
            continue

        unordered = UNORDERED_LIST_RE.match(line)
        ordered = ORDERED_LIST_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            is_ordered = ordered is not None
            content = (ordered or unordered).group(1).strip()
            if list_items and list_ordered != is_ordered:
                flush_list()
            list_ordered = is_ordered
            list_items.append(content)
            index += 1
            continue

        flush_list()
        paragraph.append(line)
        index += 1

    flush_list()
    flush_paragraph()
    flush_quote()
    if in_code and code_lines:
        html_lines.append(render_zsxq_code_block("\n".join(code_lines)))
    return "\n".join(html_lines)


def render_zsxq_html(
    title: str,
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    body = render_zsxq_blocks(markdown, image_mode=image_mode, asset_base_dir=asset_base_dir)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - 知识星球</title>
</head>
<body style="margin:0;padding:20px 16px;background:#ffffff;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;">
{body}
</body>
</html>
"""


def render_wechat_html(
    title: str,
    markdown: str,
    image_mode: str = "placeholder",
    asset_base_dir: Path | None = None,
) -> str:
    """Render a WeChat-friendly article body.

    Intentionally no auto-generated title bar and no "本文路线" outline:
    the WeChat editor already has its own title field, and any opening
    paragraph the author wants should be written explicitly in the source
    Markdown. Auto-prepending decoration was noise the user had to delete
    every time.
    """
    body = render_blocks(markdown, image_mode=image_mode, asset_base_dir=asset_base_dir)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
</head>
<body style="box-sizing:border-box;margin:0;background:#f5efe4;padding:20px 0;overflow-x:hidden;">
  <article style="width:calc(100% - 32px);max-width:720px;box-sizing:border-box;margin:0 auto;background:#ffffff;padding:38px 24px 42px;color:#1a1a1a;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;border-top:3px solid #c2410c;box-shadow:0 4px 24px rgba(120,80,30,0.05);">
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
    <span style="margin-left:12px;color:#cbd5e1;">本地图预览：wechat-preview.html · 一次性粘贴试用：wechat-embedded.html · 兜底粘贴版：wechat.html · Report: {html.escape(report_path)}</span>
  </header>
  <iframe src="wechat-preview.html" style="display:block;width:100%;height:calc(100vh - 56px);border:0;background:#fff;"></iframe>
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
  <p>优先使用 <a href="wechat.html">wechat.html</a>，它把本地图片转成 Base64 内嵌，适合一次性复制粘贴到公众号。若平台丢图，再用 <a href="image-manifest.md">image-manifest.md</a> 和 assets/ 兜底。</p>
  <iframe src="wechat.html" style="display:block;width:100%;height:80vh;border:1px solid #ddd;"></iframe>
</body>
</html>
"""


def build_platform_report(zhihu_hosted: bool = False) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for platform, profile in PLATFORM_PROFILES.items():
        recommended = profile["recommended"]
        image_mode = profile["html_image_mode"]
        image_strategy = profile["image_strategy"]
        if platform == "zhihu" and not zhihu_hosted:
            image_mode = "markdown-local"
            image_strategy = (
                "未使用 Git 图床（md2zhihu 不可用或未配置 --zhihu-asset-repo）。"
                "zhihu.md 使用本地 ../assets/ 链接，请按 image-manifest.md 从 assets/ 手工补图。"
            )
        report[platform] = {
            "label": profile["label"],
            "recommended": recommended,
            "fallback": profile["fallback"],
            "html_image_mode": image_mode,
            "editor_model": profile["editor_model"],
            "image_strategy": image_strategy,
            "code_strategy": profile["code_strategy"],
            "notes": profile["notes"],
            "sources": profile["sources"],
        }
    return report


def render_platform_guide(title: str, zhihu_hosted: bool = False) -> str:
    report = build_platform_report(zhihu_hosted=zhihu_hosted)
    lines = [
        f"# {title} 平台发布指南",
        "",
        "这个文件说明 `platforms/` 下每个平台应该优先使用哪个版本，以及发布前需要手工复核什么。",
        "",
        "| 平台 | 首选文件 | 兜底文件 | 核心处理 |",
        "| --- | --- | --- | --- |",
    ]
    for platform in PLATFORMS:
        profile = report[platform]
        lines.append(
            f"| {profile['label']} | `{profile['recommended']}` | `{profile['fallback']}` | {profile['image_strategy']} |"
        )

    lines.extend(["", "## 平台细节", ""])
    for platform in PLATFORMS:
        profile = report[platform]
        lines.append(f"### {profile['label']}")
        lines.append("")
        lines.append(f"- 编辑器判断：{profile['editor_model']}")
        lines.append(f"- 代码处理：{profile['code_strategy']}")
        for note in profile["notes"]:  # type: ignore[index]
            lines.append(f"- 注意：{note}")
        lines.append("- 来源：")
        for source in profile["sources"]:  # type: ignore[index]
            if isinstance(source, dict):
                lines.append(f"  - [{source['label']}]({source['url']})")
        lines.append("")

    lines.extend(
        [
            "## 知乎（md2zhihu + Git 图床）",
            "",
            "知乎正文由 md2zhihu 生成 `platforms/zhihu.md`：公式转知乎原生公式图，mermaid/graphviz 转图片，表格转 HTML，本地图片推送到 Git 图床并改写成 HTTPS 链接，可直接导入知乎。",
            "",
            "1. 安装依赖（macOS）：`brew install pandoc imagemagick node`、`npm install -g @mermaid-js/mermaid-cli`、`uv tool install md2zhihu --with pygments --with urllib3 --with requests --with mistune` (或 `pip install md2zhihu pygments urllib3 requests mistune`)。",
            "2. 准备一个有写权限的公共仓库（gitee/github）作为图床。",
            "3. 运行 `build_publish_package.py --zhihu-asset-repo \"https://github.com/backtomyfuture/images.git\" --overwrite`。",
            "4. 在知乎写文章页用“导入文档/粘贴 Markdown”载入 `platforms/zhihu.md`，标题单独填写。",
            "",
            "如果未安装 md2zhihu 或未配置图床，`zhihu.md` 会回退为带本地 `../assets/` 链接的版本，请按 `image-manifest.md` 从 `assets/` 手工补图。",
            "",
        ]
    )

    lines.extend(
        [
            "## 手工发布顺序",
            "",
            "1. 知乎：导入 `platforms/zhihu.md`；其他平台打开 `platforms/<平台>.html` 复制正文到编辑器。",
            "2. 确认图片是否随内容进入编辑器；若被清洗，按 `image-manifest.md` 的顺序从 `assets/` 上传或拖入图片。",
            "3. 检查代码块、标题层级、链接、图片位置和平台要求的标题/封面/标签/分类。",
            "4. 先保存草稿或预览，再发布。",
            "",
        ]
    )
    return "\n".join(lines)


def render_zsxq_quote_lab(title: str) -> str:
    safe_title = html.escape(title)
    samples = [
        (
            "A. 标准 HTML blockquote",
            "复制下面渲染出的这一段。如果成功，说明知识星球接受标准 HTML 引用。",
            "<blockquote><p><strong>引用测试 A：</strong>这是标准 blockquote + p 结构。</p></blockquote>",
        ),
        (
            "B. 裸 blockquote",
            "测试编辑器是否只接受没有段落包裹的 blockquote。",
            "<blockquote><strong>引用测试 B：</strong>这是裸 blockquote 结构。</blockquote>",
        ),
        (
            "C. ProseMirror/Tiptap 属性",
            "测试知识星球底层编辑器是否识别 data-type 属性。",
            '<blockquote data-type="blockquote"><p><strong>引用测试 C：</strong>这是带 data-type 的 blockquote。</p></blockquote>',
        ),
        (
            "D. Slate/通用 data-block 属性",
            "测试编辑器是否识别通用块类型属性。",
            '<blockquote data-block="quote"><p><strong>引用测试 D：</strong>这是带 data-block 的 blockquote。</p></blockquote>',
        ),
        (
            "E. div role blockquote",
            "测试非 blockquote 标签但带 role 的结构。",
            '<div role="blockquote"><p><strong>引用测试 E：</strong>这是 role=blockquote 的 div。</p></div>',
        ),
        (
            "F. 视觉左边框段落",
            "这不是原生引用，但能测试知识星球是否保留内联 border-left 样式。",
            '<p style="border-left:4px solid #d0d7de;padding-left:12px;"><strong>引用测试 F：</strong>这是用样式模拟的引用。</p>',
        ),
    ]
    sample_html = []
    for label, note, body in samples:
        sample_html.append(
            "<section>"
            f"<h2>{html.escape(label)}</h2>"
            f"<p>{html.escape(note)}</p>"
            f'<div class="sample">{body}</div>'
            "</section>"
        )

    markdown_single = "> **引用测试 G：** 这是纯 Markdown 单行引用。"
    markdown_multi = "> **引用测试 H：** 这是纯 Markdown 多行引用第一行。\n>\n> 第二行继续引用。"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - 知识星球引用实验</title>
  <style>
    body {{ margin:0; padding:24px; color:#111827; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif; line-height:1.75; }}
    main {{ max-width:820px; margin:0 auto; }}
    h1 {{ font-size:28px; line-height:1.35; margin:0 0 8px; }}
    h2 {{ font-size:18px; line-height:1.45; margin:28px 0 8px; }}
    p {{ margin:0 0 12px; }}
    .sample {{ margin:10px 0 18px; padding:14px 16px; border:1px solid #e5e7eb; background:#f9fafb; }}
    textarea {{ width:100%; min-height:88px; box-sizing:border-box; padding:12px; border:1px solid #d1d5db; font-size:15px; line-height:1.7; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
    .hint {{ color:#4b5563; font-size:14px; }}
  </style>
</head>
<body>
<main>
  <h1>{safe_title} - 知识星球原生引用实验</h1>
  <p class="hint">逐个只复制灰框或文本框里的样本，粘贴到知识星球长文章编辑器。若某一项显示为平台原生引用块，记录对应字母；如果都失败，说明外部粘贴无法触发原生引用，只能用正文视觉引用或手动点工具栏引用按钮。</p>
  {''.join(sample_html)}
  <section>
    <h2>G. 纯 Markdown 单行引用</h2>
    <p>请点击文本框，Cmd+A / Ctrl+A 选中文本框内容后复制。这个会尽量以纯文本进入剪贴板。</p>
    <textarea>{html.escape(markdown_single)}</textarea>
  </section>
  <section>
    <h2>H. 纯 Markdown 多行引用</h2>
    <p>测试知识星球是否在粘贴纯 Markdown 时解析多行 blockquote。</p>
    <textarea>{html.escape(markdown_multi)}</textarea>
  </section>
  <section>
    <h2>I. 当前稳定兜底</h2>
    <p>这是当前主稿采用的视觉引用。它不是原生引用，但粘贴稳定。</p>
    <div class="sample"><p><strong>▍引用测试 I：</strong>这是视觉引用兜底。</p></div>
  </section>
</main>
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


MERMAID_BLOCK_RE = re.compile(
    r"^([ \t]{0,3})```\s*mermaid\s*\n(.*?)(?:\n)?^\1```[ \t]*$\n?",
    re.MULTILINE | re.DOTALL,
)


def _render_mermaid_to_png(
    code: str,
    output_dir: Path,
    binary: str,
) -> Path | None:
    """Render a single mermaid snippet to a PNG via mmdc.

    Returns the absolute output path on success, or None on failure. The
    filename is content-addressed so re-running the build reuses the same
    image and produces stable diffs.
    """
    import hashlib

    diagrams_dir = output_dir / "assets" / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]
    out_path = diagrams_dir / f"mermaid_{digest}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    with tempfile.NamedTemporaryFile(
        "w", suffix=".mmd", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(code)
        tmp_in = tf.name
    try:
        completed = subprocess.run(
            [
                binary,
                "-i",
                tmp_in,
                "-o",
                str(out_path),
                "-b",
                "white",
                "-s",
                "2",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    finally:
        try:
            os.unlink(tmp_in)
        except OSError:
            pass

    if completed.returncode != 0 or not out_path.exists():
        return None
    return out_path


def convert_mermaid_blocks_if_available(
    markdown: str,
    output_dir: Path,
) -> tuple[str, list[dict[str, str]], list[dict[str, object]]]:
    """Replace ```mermaid``` fenced blocks with PNG image references.

    Uses the mermaid-cli binary (`mmdc`) when available, mirroring how
    md2zhihu handles diagrams. On success the fenced block is replaced
    with a standard Markdown image so every downstream renderer (WeChat,
    Toutiao, Zsxq, SMZDM, Zhihu via md2zhihu) embeds the same picture.
    On failure or when `mmdc` is missing, the block is left untouched and
    a single warning is emitted so the reader is not stuck staring at raw
    mermaid source code.
    """
    if "```mermaid" not in markdown and "``` mermaid" not in markdown:
        return markdown, [], []

    binary = shutil.which("mmdc")
    blocks = list(MERMAID_BLOCK_RE.finditer(markdown))
    if not blocks:
        return markdown, [], []

    warnings: list[dict[str, object]] = []
    if not binary:
        warnings.append(
            warning(
                "mermaid_renderer_missing",
                "Found mermaid code blocks but mmdc (mermaid-cli) was not on PATH; "
                "raw mermaid source will appear in the article. Install with "
                "`npm install -g @mermaid-js/mermaid-cli` and rebuild to render diagrams as PNG.",
                count=len(blocks),
            )
        )
        return markdown, [], warnings

    assets: list[dict[str, str]] = []
    rendered: list[tuple[re.Match[str], Path]] = []
    failures = 0
    for match in blocks:
        code = match.group(2).strip("\n")
        if not code.strip():
            continue
        out_path = _render_mermaid_to_png(code, output_dir, binary)
        if out_path is None:
            failures += 1
            continue
        rendered.append((match, out_path))
        assets.append(
            {
                "source": "generated_mermaid",
                "output": str(out_path.relative_to(output_dir)),
            }
        )

    if failures:
        warnings.append(
            warning(
                "mermaid_render_failed",
                f"mmdc failed to render {failures} mermaid block(s); raw source kept inline.",
                failures=failures,
            )
        )

    if not rendered:
        return markdown, assets, warnings

    # Walk replacements back-to-front so earlier indices stay valid.
    result = markdown
    for match, out_path in reversed(rendered):
        rel = out_path.relative_to(output_dir).as_posix()
        replacement = f"\n![diagram]({rel})\n"
        result = result[: match.start()] + replacement + result[match.end() :]
    return result, assets, warnings


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
            # Warm cream header + terracotta accent so rasterized tables
            # blend into the WeChat magazine column instead of looking like
            # a pasted-in dark engineering screenshot.
            "magazine",
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
        "Open wechat.html in your browser to preview; copy/paste it into the WeChat Official Account editor.",
        "For Toutiao/Zsxq/SMZDM, open platforms/<name>.html and paste into that platform's article editor (title is entered separately).",
        "For Zhihu, import platforms/zhihu.md via the Zhihu editor's '导入文档/粘贴 Markdown'; md2zhihu hosts images on the configured --zhihu-asset-repo git repo.",
        "If md2zhihu is unavailable or no --zhihu-asset-repo was set, zhihu.md uses local ../assets/ links; upload images in order using image-manifest.md.",
        "If another platform drops embedded images after paste, use image-manifest.md to upload or drag images from assets/ in the original order.",
    ]
    if any(item.get("code") == "remote_image_download_failed" for item in warnings):
        steps.append(
            "Some remote images failed to download (e.g. expired Notion S3 presigned URLs). Refresh the source export, save the images into the same folder as your Markdown, and re-run the build."
        )
    if any(item.get("code") == "md2zhihu_not_installed" for item in warnings):
        steps.append(
            "Install md2zhihu for native Zhihu math/diagram conversion and git-hosted images: "
            "brew install pandoc imagemagick node && npm i -g @mermaid-js/mermaid-cli && uv tool install md2zhihu --with pygments --with urllib3 --with requests --with mistune (or pip install md2zhihu pygments urllib3 requests mistune)."
        )
    if warnings:
        steps.append("Review report.json warnings before publishing.")
    return steps


def _default_zhihu_converter() -> Callable[..., object]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import zhihu_md2zhihu  # noqa: WPS433 - local helper shipped with this skill

    return zhihu_md2zhihu.convert


def build_zhihu_markdown(
    title: str,
    source_markdown: str,
    output_dir: Path,
    *,
    asset_repo: str | None,
    md2zhihu_bin: str | None = None,
    download: bool = True,
    converter: Optional[Callable[..., object]] = None,
) -> tuple[str, bool, list[dict[str, object]]]:
    """Produce ``platforms/zhihu.md`` via md2zhihu, with a plain-Markdown fallback.

    Returns ``(relative_output_path, hosted, warnings)`` where ``hosted`` is
    True only when md2zhihu ran and uploaded images to a git asset repo. The
    Zhihu conversion must never crash the overall build: every failure path
    writes a local-link ``zhihu.md`` and records a warning instead.
    """
    warnings: list[dict[str, object]] = []
    dest = output_dir / "platforms" / "zhihu.md"

    def write_local_fallback() -> str:
        # zhihu.md lives under platforms/, so local asset links need ../assets/.
        fallback_md = rewrite_asset_paths_for_platforms(source_markdown)
        body = fallback_md if fallback_md.endswith("\n") else fallback_md + "\n"
        write_text(dest, body)
        return "platforms/zhihu.md"

    if not asset_repo:
        warnings.append(warning(
            "zhihu_asset_repo_missing",
            "未配置 --zhihu-asset-repo，知乎图片未托管到 Git 图床；zhihu.md 使用本地 ../assets/ 链接，"
            "请按 image-manifest.md 从 assets/ 手工补图。",
        ))
        return write_local_fallback(), False, warnings

    try:
        convert = converter or _default_zhihu_converter()
    except Exception as exc:  # import failure should degrade gracefully
        warnings.append(warning("md2zhihu_not_installed", f"加载 md2zhihu 封装失败：{exc}"))
        return write_local_fallback(), False, warnings

    # md2zhihu resolves image paths relative to the source Markdown's directory,
    # so write the source beside the output's assets/ folder.
    zhihu_src = output_dir / ".zhihu-src.md"
    src_body = source_markdown if source_markdown.endswith("\n") else source_markdown + "\n"
    write_text(zhihu_src, src_body)
    result: object | None = None
    try:
        result = convert(
            zhihu_src,
            dest,
            asset_repo=asset_repo,
            platform="zhihu",
            download=download,
            md2zhihu_bin=md2zhihu_bin,
        )
    except Exception as exc:  # never let Zhihu conversion crash the build
        warnings.append(warning("zhihu_md2zhihu_failed", f"md2zhihu 调用异常：{exc}"))
    finally:
        zhihu_src.unlink(missing_ok=True)

    if result is not None and getattr(result, "ok", False) and dest.exists():
        return "platforms/zhihu.md", True, warnings

    error_text = getattr(result, "error", None) if result is not None else None
    if error_text:
        code = "md2zhihu_not_installed" if "未找到 md2zhihu" in str(error_text) else "zhihu_md2zhihu_failed"
        warnings.append(warning(code, str(error_text)))
    return write_local_fallback(), False, warnings


def build_package(
    source_path: Path | str,
    output_dir: Path | str,
    overwrite: bool = False,
    strict: bool = False,
    table_mode: str = "auto",
    style: str = "magazine",
    zhihu_asset_repo: str | None = None,
    md2zhihu_bin: str | None = None,
    zhihu_download: bool = True,
    zhihu_converter: Optional[Callable[..., object]] = None,
    open_after_build: bool = False,
    open_target: str = "zhihu",
    download_remote_images: bool = True,
    remote_downloader: Optional[Callable[[str, Path, int], Optional[Path]]] = None,
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
    normalized, assets, image_warnings = rewrite_images_to_assets(
        body,
        source.parent,
        output / "assets",
        download_remote=download_remote_images,
        remote_downloader=remote_downloader,
    )
    normalized = normalize_notion_quote_callouts(normalized)
    warnings.extend(image_warnings)
    warnings.extend(detect_raw_html_warnings(normalized))

    # Pre-render mermaid diagrams to PNG so every platform (WeChat, Toutiao,
    # Zsxq, SMZDM, and Zhihu via md2zhihu) embeds the same picture. Without
    # this the WeChat HTML would show raw `xychart-beta / line ...` source
    # to readers, since the magazine renderer has no in-process mermaid
    # support. We run this BEFORE the Zhihu snapshot so md2zhihu also picks
    # up the rendered image instead of re-rasterizing the source.
    normalized, mermaid_assets, mermaid_warnings = convert_mermaid_blocks_if_available(normalized, output)
    assets.extend(mermaid_assets)
    warnings.extend(mermaid_warnings)

    # Snapshot the image-localized body BEFORE table->PNG conversion: md2zhihu
    # renders Markdown tables to native HTML for Zhihu, which beats shipping a
    # rasterized table image, so the Zhihu pipeline gets the un-rasterized body.
    zhihu_source_markdown = normalized

    table_report = {"converted": 0, "kept": count_pipe_tables(normalized), "mode": table_mode}
    if table_mode != "never":
        normalized, table_report, table_warnings, table_assets = convert_tables_if_requested(normalized, output, table_mode)
        warnings.extend(table_warnings)
        assets.extend(table_assets)

    if strict and warnings:
        codes = ", ".join(str(item["code"]) for item in warnings)
        raise RuntimeError(f"Strict mode failed with warnings: {codes}")

    image_manifest = extract_image_manifest(normalized)

    # WeChat: only emit the one paste-ready Base64 file. The placeholder /
    # preview / copy-helper files were noisy intermediates that the user
    # rarely opened.
    wechat_html = render_wechat_html(title, normalized, image_mode="data", asset_base_dir=output)
    write_text(output / "wechat.html", wechat_html)

    outputs: list[str] = ["wechat.html"]

    # Toutiao / Zsxq / SMZDM still share the magazine HTML renderer.
    platform_outputs: list[str] = []
    platform_markdown = rewrite_asset_paths_for_platforms(normalized)
    for platform in RICH_HTML_PLATFORMS:
        platform_content = markdown_for_platform(platform_markdown, platform)
        html_relative = f"platforms/{platform}.html"
        image_mode = str(PLATFORM_PROFILES[platform].get("html_image_mode", "placeholder"))
        write_text(
            output / html_relative,
            render_platform_html(
                platform,
                title,
                platform_content,
                image_mode=image_mode,
                asset_base_dir=output / "platforms",
            ),
        )
        platform_outputs.append(html_relative)

    outputs.extend(platform_outputs)

    # Zhihu: delegate to md2zhihu to produce an import-ready Markdown file with
    # native equation images, mermaid/graphviz figures and git-hosted images.
    zhihu_relative, zhihu_hosted, zhihu_warnings = build_zhihu_markdown(
        title,
        zhihu_source_markdown,
        output,
        asset_repo=zhihu_asset_repo,
        md2zhihu_bin=md2zhihu_bin,
        download=zhihu_download,
        converter=zhihu_converter,
    )
    warnings.extend(zhihu_warnings)
    outputs.append(zhihu_relative)

    # Always ship a small image order list when local images exist. The Zhihu
    # local-link fallback needs it, and other editors may drop embedded images.
    if image_manifest:
        write_text(output / "image-manifest.md", render_image_manifest(title, image_manifest))
        outputs.append("image-manifest.md")

    platform_report = build_platform_report(zhihu_hosted=zhihu_hosted)

    report: dict[str, object] = {
        "source": str(source),
        "title": title,
        "outputs": outputs,
        "assets": assets,
        "image_manifest": image_manifest,
        "platforms": platform_report,
        "zhihu": {
            "engine": "md2zhihu",
            "output": zhihu_relative,
            "asset_repo": zhihu_asset_repo,
            "hosted": zhihu_hosted,
        },
        "tables": table_report,
        "warnings": warnings,
        "next_steps": build_next_steps(warnings),
    }
    write_text(output / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    if open_after_build:
        target_map = {
            "zhihu": "platforms/zhihu.md",
            "wechat": "wechat.html",
            "toutiao": "platforms/toutiao.html",
            "zsxq": "platforms/zsxq.html",
            "smzdm": "platforms/smzdm.html",
        }
        chosen_rel = target_map.get(open_target, "platforms/zhihu.md")
        chosen_path = output / chosen_rel
        if chosen_path.exists():
            _open_in_browser(chosen_path)
            report["opened"] = str(chosen_path)
    return report


def _open_in_browser(path: Path) -> None:
    """Launch the host OS browser/file viewer for the given HTML file."""
    uri = path.resolve().as_uri()
    if sys.platform == "darwin":
        cmd = ["open", str(path)]
    elif sys.platform.startswith("win"):
        cmd = ["cmd", "/c", "start", "", uri]
    else:
        cmd = ["xdg-open", str(path)]
    try:
        subprocess.run(cmd, check=False, capture_output=True)
    except Exception as exc:
        print(f"[open] failed to open {path}: {exc}", file=sys.stderr)


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
    parser.add_argument(
        "--zhihu-asset-repo",
        default=os.environ.get("ZHIHU_ASSET_REPO") or os.environ.get("MD2ZHIHU_ASSET_REPO"),
        help=(
            "Git asset repo md2zhihu pushes Zhihu images to, e.g. "
            '"https://github.com/backtomyfuture/images.git" or '
            '"git@github.com:backtomyfuture/images.git". '
            "Defaults to $ZHIHU_ASSET_REPO / $MD2ZHIHU_ASSET_REPO. "
            "Without it, zhihu.md falls back to local ../assets/ links."
        ),
    )
    parser.add_argument(
        "--md2zhihu-bin",
        help="Explicit path to the md2zhihu executable (defaults to the one on PATH).",
    )
    parser.add_argument(
        "--no-zhihu-download",
        action="store_true",
        help="Do not let md2zhihu fetch remote http(s) image URLs while converting Zhihu Markdown.",
    )
    parser.add_argument(
        "--no-download-remote-images",
        action="store_true",
        help="Disable automatically downloading remote (http(s)) images into assets/. By default the build fetches every Markdown image URL (including Notion S3 presigned URLs that expire within an hour) so each platform HTML ends up with stable local assets instead of expiring links.",
    )
    parser.add_argument(
        "--open",
        dest="open_after_build",
        action="store_true",
        default=True,
        help="After build, open the chosen HTML in the system browser (default).",
    )
    parser.add_argument(
        "--no-open",
        dest="open_after_build",
        action="store_false",
        help="Do not auto-open any HTML after build.",
    )
    parser.add_argument(
        "--open-target",
        choices=["zhihu", "wechat", "toutiao", "zsxq", "smzdm"],
        default="zhihu",
        help="Which output to open after build (default: zhihu opens platforms/zhihu.md for import).",
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
            zhihu_asset_repo=args.zhihu_asset_repo,
            md2zhihu_bin=args.md2zhihu_bin,
            zhihu_download=not args.no_zhihu_download,
            open_after_build=args.open_after_build,
            open_target=args.open_target,
            download_remote_images=not args.no_download_remote_images,
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
