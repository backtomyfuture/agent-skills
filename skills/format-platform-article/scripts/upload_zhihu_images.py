#!/usr/bin/env python3
"""Batch-upload article images to Zhihu and emit a remote URL map."""

from __future__ import annotations

import argparse
import base64
import email.utils
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie, CookieJar
from pathlib import Path


ZHIHU_IMAGE_API = "https://api.zhihu.com/images"
ZHIHU_OSS_UPLOAD_URL = "https://zhihu-pics-upload.zhimg.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
REQUIRED_COOKIES = {"z_c0", "_xsrf", "d_c0"}


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


def load_cookie_file(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(name): str(value) for name, value in data.items()}
        if isinstance(data, list):
            cookies: dict[str, str] = {}
            for item in data:
                if isinstance(item, dict) and item.get("name") and item.get("value"):
                    cookies[str(item["name"])] = str(item["value"])
            return cookies
        raise ValueError("Cookie JSON must be an object or browser cookie array")
    return parse_cookie_header(text)


def cookie_from_agent_browser(session_name: str) -> dict[str, str]:
    script = r"""(() => ({ cookie: document.cookie, url: location.href }))()"""
    completed = subprocess.run(
        ["agent-browser", "--session-name", session_name, "eval", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {}
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {}
    cookie = payload.get("cookie") if isinstance(payload, dict) else None
    return parse_cookie_header(cookie) if isinstance(cookie, str) else {}


def load_cookies(args: argparse.Namespace) -> dict[str, str]:
    if args.cookie:
        cookies = parse_cookie_header(args.cookie)
    elif args.cookie_file:
        cookies = load_cookie_file(args.cookie_file)
    elif os.environ.get("ZHIHU_COOKIE"):
        cookies = parse_cookie_header(os.environ["ZHIHU_COOKIE"])
    elif args.agent_browser_session:
        cookies = cookie_from_agent_browser(args.agent_browser_session)
    else:
        default = Path.home() / ".zhihu-cli" / "cookies.json"
        cookies = load_cookie_file(default) if default.exists() else {}

    missing = sorted(REQUIRED_COOKIES - set(cookies))
    if missing:
        raise RuntimeError(
            "Missing Zhihu cookies: "
            + ", ".join(missing)
            + ". Use pyzhihu-cli login, --cookie-file, --cookie, or ZHIHU_COOKIE."
        )
    return cookies


def build_opener(cookies: dict[str, str]) -> urllib.request.OpenerDirector:
    jar = CookieJar()
    for name, value in cookies.items():
        jar.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=".zhihu.com",
                domain_specified=True,
                domain_initial_dot=True,
                path="/",
                path_specified=True,
                secure=True,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def base_headers(xsrf: str) -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.zhihu.com",
        "Referer": "https://www.zhihu.com/",
        "x-xsrftoken": xsrf,
    }


def json_request(
    opener: urllib.request.OpenerDirector,
    url: str,
    headers: dict[str, str],
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 30,
) -> dict:
    data = None
    request_headers = dict(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Zhihu request failed with HTTP {exc.code}: {detail}") from exc


def register_image(opener: urllib.request.OpenerDirector, headers: dict[str, str], image_data: bytes, source: str) -> dict:
    md5_hex = hashlib.md5(image_data).hexdigest()
    return json_request(
        opener,
        ZHIHU_IMAGE_API,
        headers,
        method="POST",
        payload={"image_hash": md5_hex, "source": source},
        timeout=30,
    )


def upload_to_oss(obj_key: str, image_data: bytes, upload_token: dict, content_type: str) -> None:
    security_token = upload_token["access_token"]
    access_id = upload_token["access_id"]
    access_key = upload_token["access_key"]
    date = email.utils.formatdate(usegmt=True)
    string_to_sign = (
        f"PUT\n\n{content_type}\n{date}\n"
        f"x-oss-security-token:{security_token}\n"
        f"/zhihu-pics/{obj_key}"
    )
    signature = base64.b64encode(
        hmac.new(access_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    request = urllib.request.Request(
        f"{ZHIHU_OSS_UPLOAD_URL}/{urllib.parse.quote(obj_key)}",
        data=image_data,
        method="PUT",
        headers={
            "Content-Type": content_type,
            "Date": date,
            "x-oss-security-token": security_token,
            "Authorization": f"OSS {access_id}:{signature}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise RuntimeError(f"OSS upload failed with HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"OSS upload failed with HTTP {exc.code}: {detail}") from exc


def poll_image(opener: urllib.request.OpenerDirector, headers: dict[str, str], image_id: str, max_attempts: int = 60, interval: float = 2.0) -> dict:
    last_status: str | None = None
    for attempt in range(max_attempts):
        data = json_request(opener, f"{ZHIHU_IMAGE_API}/{image_id}", headers, timeout=30)
        status = data.get("status")
        if status == "success" and (data.get("src") or data.get("original_src")):
            return data
        if status != last_status:
            print(f"[zhihu-poll] {image_id} status={status!r} (attempt {attempt + 1}/{max_attempts})", file=sys.stderr, flush=True)
            last_status = status
        time.sleep(interval)
    raise RuntimeError(f"Zhihu image processing timed out after {int(max_attempts * interval)}s: {image_id}")


def upload_zhihu_image(
    opener: urllib.request.OpenerDirector,
    headers: dict[str, str],
    file_path: Path,
    source: str,
) -> str:
    if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported Zhihu image type: {file_path}")
    image_data = file_path.read_bytes()
    registered = register_image(opener, headers, image_data, source)
    upload_file = registered.get("upload_file") or {}
    image_id = upload_file.get("image_id")
    if not image_id:
        raise RuntimeError(f"Zhihu image registration returned no image_id: {registered}")
    state = upload_file.get("state")
    if state == 2:
        object_key = upload_file["object_key"]
        # Zhihu's web upload flow signs the OSS object with image/jpeg in known
        # clients; keep the header stable unless the endpoint changes.
        content_type = "image/jpeg"
        upload_to_oss(object_key, image_data, registered["upload_token"], content_type)
    elif state != 1:
        raise RuntimeError(f"Unexpected Zhihu image upload state: {state}")
    info = poll_image(opener, headers, str(image_id))
    src = info.get("src") or info.get("original_src")
    return str(src) if src else ""


def load_template(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Template must be a JSON object")
    return {str(key): str(value) for key, value in data.items()}


def resolve_local_image(template_path: Path, key: str) -> Path:
    raw = key.strip()
    candidates: list[Path] = []
    path = Path(raw)
    if path.is_absolute():
        candidates.append(path)
    candidates.append((template_path.parent / raw).resolve())
    candidates.append((template_path.parent.parent / raw).resolve())
    normalized = raw
    while normalized.startswith("../"):
        normalized = normalized[3:]
    candidates.append((template_path.parent.parent / normalized).resolve())
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Image for template key not found: {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch upload Zhihu article images and write a remote image map.")
    parser.add_argument("--template", type=Path, required=True, help="zhihu-image-map.template.json")
    parser.add_argument("--output", type=Path, required=True, help="Output zhihu-image-map.json")
    parser.add_argument("--cookie", help="Raw Zhihu Cookie header containing z_c0, _xsrf, and d_c0")
    parser.add_argument("--cookie-file", type=Path, help="JSON or raw-cookie file")
    parser.add_argument("--agent-browser-session", help="Read document.cookie from a logged-in agent-browser session")
    parser.add_argument("--source", default="article", help="Zhihu upload source, default: article")
    parser.add_argument("--reuse-existing", action="store_true", help="Keep URLs already present in the template")
    args = parser.parse_args(argv)

    try:
        cookies = load_cookies(args)
        opener = build_opener(cookies)
        headers = base_headers(cookies["_xsrf"])
        template = load_template(args.template)
        mapping: dict[str, str] = {}
        for index, (key, existing_url) in enumerate(template.items(), start=1):
            if args.reuse_existing and existing_url.startswith("https://"):
                mapping[key] = existing_url
                continue
            local_image = resolve_local_image(args.template, key)
            print(f"[{index}/{len(template)}] Upload {local_image.name}", file=sys.stderr)
            mapping[key] = upload_zhihu_image(opener, headers, local_image, args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "images": len(mapping)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
