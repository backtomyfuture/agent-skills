#!/usr/bin/env python3
"""Capture Zhihu login cookies into ~/.zhihu-cli/cookies.json.

build_publish_package.py needs three Zhihu cookies (`z_c0`, `_xsrf`, `d_c0`)
to push images through the Zhihu image API. `z_c0` is HttpOnly, so plain
`document.cookie` cannot see it; we use `agent-browser` (Playwright/CDP)
which reads the full cookie jar via `chrome.cookies` semantics.

Usage:
  python3 zhihu_login.py                # opens a persistent headed browser
                                        # session at zhihu.com/signin
  python3 zhihu_login.py --cookie "z_c0=...; _xsrf=...; d_c0=..."  # paste

The first time you run it you log in once; the agent-browser session named
`zhihu-cookies` persists, so subsequent runs reuse it silently.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


REQUIRED_COOKIES = ("z_c0", "_xsrf", "d_c0")
DEFAULT_OUTPUT = Path.home() / ".zhihu-cli" / "cookies.json"
DEFAULT_SESSION = "zhihu-cookies"
ZHIHU_SIGNIN = "https://www.zhihu.com/signin"
ZHIHU_HOME = "https://www.zhihu.com/"


def parse_cookie_header(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        name, cookie_value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = cookie_value.strip()
    return cookies


def agent_browser_cookies(session: str, timeout: int = 30) -> dict[str, str]:
    """Read all cookies for the agent-browser session and flatten to name=value.

    `agent-browser cookies get --json` returns the full cookie record including
    HttpOnly cookies; we keep only the values keyed by name.
    """
    completed = subprocess.run(
        ["agent-browser", "--session-name", session, "cookies", "get", "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "agent-browser cookies get failed:\n"
            f"stdout: {completed.stdout.strip()}\nstderr: {completed.stderr.strip()}"
        )
    raw = completed.stdout.strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not payload.get("success"):
        raise RuntimeError(f"agent-browser returned error: {payload.get('error')}")
    cookies: dict[str, str] = {}
    for item in (payload.get("data", {}) or {}).get("cookies", []):
        name = item.get("name")
        value = item.get("value")
        domain = (item.get("domain") or "").lstrip(".")
        if not name or value is None:
            continue
        if "zhihu.com" not in domain:
            continue
        cookies[name] = str(value)
    return cookies


def agent_browser_open(session: str, url: str, headed: bool, timeout: int = 90) -> None:
    cmd = ["agent-browser", "--session-name", session]
    if headed:
        cmd.append("--headed")
    cmd.extend(["open", url])
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    if "Executable doesn't exist" in combined:
        raise RuntimeError(
            "Playwright Chromium not installed for agent-browser. Run: "
            "cd /Users/jarod/.factory/tools/agent-browser/dist && "
            "node node_modules/playwright-core/cli.js install chromium"
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "agent-browser open failed:\n"
            f"stdout: {completed.stdout.strip()}\nstderr: {completed.stderr.strip()}"
        )


def capture_cookies_via_agent_browser(session: str, login_timeout: int, headed: bool) -> dict[str, str]:
    if shutil.which("agent-browser") is None:
        raise RuntimeError(
            "agent-browser not found on PATH. Install it from "
            "https://github.com/factory-ai/agent-browser, or use --cookie to paste manually."
        )

    # First: just try reading cookies from the persistent session. If the
    # user already logged in on a previous run, z_c0 is already there.
    try:
        cookies = agent_browser_cookies(session)
    except Exception:
        cookies = {}
    if all(name in cookies for name in REQUIRED_COOKIES):
        return cookies

    # Otherwise open the signin page (headed by default) and poll until the
    # user finishes login or the timeout expires.
    print(
        "[zhihu_login] 打开浏览器登录知乎。在弹出的窗口里完成登录后保持窗口开启，"
        "脚本会自动检测到 z_c0 后退出。",
        file=sys.stderr,
    )
    agent_browser_open(session, ZHIHU_SIGNIN, headed=headed)

    deadline = time.time() + max(login_timeout, 5)
    while time.time() < deadline:
        try:
            cookies = agent_browser_cookies(session)
        except Exception as exc:
            print(f"[zhihu_login] 暂时读取 Cookie 失败：{exc}", file=sys.stderr)
            cookies = {}
        if all(name in cookies for name in REQUIRED_COOKIES):
            return cookies
        remaining = int(deadline - time.time())
        print(
            f"[zhihu_login] 等待登录中… 已抓到 {len(cookies)} 个 cookie，"
            f"还缺：{', '.join(name for name in REQUIRED_COOKIES if name not in cookies)}；"
            f"剩余 {remaining}s。",
            file=sys.stderr,
        )
        time.sleep(4)

    return cookies


def write_cookie_file(cookies: dict[str, str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        output_path.chmod(0o600)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Zhihu cookies into ~/.zhihu-cli/cookies.json so the "
            "publish package builder can auto-upload images to Zhihu."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination cookie JSON file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="agent-browser persistent session name (default: zhihu-cookies).",
    )
    parser.add_argument(
        "--cookie",
        help="Skip the browser and use the supplied 'name=value; name=value' string.",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        help="Skip the browser and read a 'Cookie:' style header from this file.",
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=300,
        help="Seconds to wait for required cookies to appear while you log in (default: 300).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Open the browser headless (default is headed so you can log in).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing cookie file without prompting.",
    )
    args = parser.parse_args(argv)

    output_path = args.output.expanduser().resolve()
    if output_path.exists() and not args.force:
        print(
            f"[zhihu_login] {output_path} 已存在；如需覆盖请加 --force。",
            file=sys.stderr,
        )

    try:
        if args.cookie:
            cookies = parse_cookie_header(args.cookie)
        elif args.cookie_file:
            cookies = parse_cookie_header(args.cookie_file.read_text(encoding="utf-8"))
        elif os.environ.get("ZHIHU_COOKIE"):
            cookies = parse_cookie_header(os.environ["ZHIHU_COOKIE"])
        else:
            cookies = capture_cookies_via_agent_browser(
                args.session,
                args.login_timeout,
                headed=not args.headless,
            )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    missing = [name for name in REQUIRED_COOKIES if name not in cookies]
    if missing:
        print(
            "[zhihu_login] 缺少 Cookie："
            + ", ".join(missing)
            + "。请确认浏览器里已登录知乎，或直接用 --cookie 粘贴 DevTools 里的完整 Cookie 字符串。",
            file=sys.stderr,
        )
        return 1

    write_cookie_file(cookies, output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "cookies": sorted(cookies.keys()),
                "required_present": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
