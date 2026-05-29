#!/usr/bin/env python3
"""Wrap the ``md2zhihu`` CLI to produce a Zhihu-import Markdown file.

The publish-package builder delegates the entire Zhihu pipeline to
``md2zhihu`` (https://github.com/drmingdrmer/md2zhihu). md2zhihu converts a
Markdown file into a single self-contained Markdown for Zhihu's import/paste
flow, with three signature transforms the in-house renderer never did:

- LaTeX ``$...$`` / ``$$...$$`` -> native Zhihu equation images
  (``https://www.zhihu.com/equation?tex=...``), which render as real math.
- ``mermaid`` / ``graphviz`` fenced blocks -> rendered images.
- Markdown tables -> HTML, and local images -> uploaded to a git asset repo
  (gitee.com / github.com) and referenced by raw HTTPS URL.

This module only shells out to the installed ``md2zhihu`` binary; it never
imports md2zhihu as a library so the heavy optional dependencies
(pandoc / imagemagick / node / mermaid-cli) stay out of this skill's import
path. A failed or unavailable conversion must never crash the caller — it
returns a structured result the builder turns into a warning plus a plain
Markdown fallback.

System requirements for the hosted path (macOS):

    brew install pandoc imagemagick node
    npm install -g @mermaid-js/mermaid-cli
    uv tool install md2zhihu --with pygments --with urllib3 --with requests --with mistune (或 pip install md2zhihu pygments urllib3 requests mistune)

md2zhihu does not support Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


INSTALL_HINT = (
    "未找到 md2zhihu。安装方式（macOS）："
    "`brew install pandoc imagemagick node`，"
    "`npm install -g @mermaid-js/mermaid-cli`，"
    "`uv tool install md2zhihu --with pygments --with urllib3 --with requests --with mistune` (或 `pip install md2zhihu pygments urllib3 requests mistune`)。md2zhihu 不支持 Windows。"
)
ASSET_REPO_HINT = (
    "未提供知乎 Git 图床仓库。请用 --zhihu-asset-repo 传入一个有写权限的公共仓库，"
    '例如 "git@github.com:用户名/仓库.git@分支" 或 '
    '"https://用户名:令牌@gitee.com/用户名/仓库.git"。'
)
DEFAULT_TIMEOUT_SECONDS = 600


@dataclass
class ConvertResult:
    """Outcome of a single md2zhihu invocation."""

    ok: bool
    md_output: Path | None = None
    error: str | None = None
    local_mode: bool = False
    asset_repo: str | None = None
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "md_output": str(self.md_output) if self.md_output else None,
            "error": self.error,
            "local_mode": self.local_mode,
            "asset_repo": self.asset_repo,
            "command": self.command,
        }


def find_md2zhihu(explicit: str | os.PathLike[str] | None = None) -> str | None:
    """Return a usable ``md2zhihu`` executable path, or ``None``."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
        resolved = shutil.which(str(explicit))
        if resolved:
            return resolved
        return None
    return shutil.which("md2zhihu")


def convert(
    source_md: Path | str,
    dest_md: Path | str,
    *,
    asset_repo: str | None = None,
    platform: str = "zhihu",
    download: bool = True,
    code_width: int | None = None,
    md2zhihu_bin: str | os.PathLike[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> ConvertResult:
    """Run md2zhihu on ``source_md`` and write the converted Markdown to ``dest_md``.

    Image references in ``source_md`` are resolved relative to the file's own
    directory, so the caller should write the source Markdown beside its
    ``assets/`` folder (e.g. ``<output>/.zhihu-src.md`` next to
    ``<output>/assets/``).

    The conversion runs with the source file's directory as the working
    directory so relative ``assets/...`` paths resolve regardless of how the
    binary computes them.
    """
    source = Path(source_md).resolve()
    dest = Path(dest_md).resolve()
    binary = find_md2zhihu(md2zhihu_bin)
    if binary is None:
        return ConvertResult(ok=False, error=INSTALL_HINT, asset_repo=asset_repo)
    if not source.exists():
        return ConvertResult(ok=False, error=f"知乎源 Markdown 不存在：{source}", asset_repo=asset_repo)

    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="md2zhihu-") as tmp:
        work_dir = Path(tmp) / "_md2"
        command = [
            binary,
            source.name,
            "--platform",
            platform,
            "--output-dir",
            str(work_dir),
            "--md-output",
            str(dest),
        ]
        if asset_repo:
            command.extend(["--repo", asset_repo])
        if download:
            command.append("--download")
        if code_width is not None:
            command.extend(["--code-width", str(code_width)])

        try:
            completed = subprocess.run(
                command,
                cwd=str(source.parent),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError:
            return ConvertResult(ok=False, error=INSTALL_HINT, asset_repo=asset_repo, command=command)
        except subprocess.TimeoutExpired:
            return ConvertResult(
                ok=False,
                error=f"md2zhihu 转换超时（>{timeout}s），通常是 Git 推送或 mermaid 渲染卡住。",
                asset_repo=asset_repo,
                command=command,
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"退出码 {completed.returncode}"
            return ConvertResult(
                ok=False,
                error=f"md2zhihu 转换失败：{detail}",
                asset_repo=asset_repo,
                local_mode=asset_repo is None,
                stdout=stdout,
                stderr=stderr,
                command=command,
            )
        if not dest.exists():
            return ConvertResult(
                ok=False,
                error="md2zhihu 返回成功但未生成输出文件。",
                asset_repo=asset_repo,
                local_mode=asset_repo is None,
                stdout=stdout,
                stderr=stderr,
                command=command,
            )
        return ConvertResult(
            ok=True,
            md_output=dest,
            asset_repo=asset_repo,
            local_mode=asset_repo is None,
            stdout=stdout,
            stderr=stderr,
            command=command,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Markdown file to Zhihu-import Markdown via md2zhihu."
    )
    parser.add_argument("source", type=Path, help="Source Markdown file (body, local image paths).")
    parser.add_argument("--output", type=Path, required=True, help="Destination zhihu.md path.")
    parser.add_argument(
        "--asset-repo",
        help='Git asset repo for image hosting, e.g. "git@github.com:user/repo.git@branch".',
    )
    parser.add_argument("--platform", default="zhihu", help="md2zhihu target platform (default: zhihu).")
    parser.add_argument("--no-download", action="store_true", help="Do not let md2zhihu fetch remote image URLs.")
    parser.add_argument("--code-width", type=int, help="Code image width passed to md2zhihu.")
    parser.add_argument("--md2zhihu-bin", help="Explicit md2zhihu executable path.")
    args = parser.parse_args(argv)

    result = convert(
        args.source,
        args.output,
        asset_repo=args.asset_repo,
        platform=args.platform,
        download=not args.no_download,
        code_width=args.code_width,
        md2zhihu_bin=args.md2zhihu_bin,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    if not result.ok and result.error:
        print(result.error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
