#!/usr/bin/env python3
"""Batch-upload article images to Markdown Nice and emit a remote URL map."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


MDNICE_UPLOAD_URL = "https://api.mdnice.com/file/user/upload"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}


def normalize_token(token: str) -> str:
    value = token.strip()
    if value.lower().startswith("bearer "):
        return value
    return f"Bearer {value}"


def load_token(args: argparse.Namespace) -> str:
    if args.token:
        return normalize_token(args.token)
    if args.token_file:
        return normalize_token(Path(args.token_file).read_text(encoding="utf-8").strip())
    env_token = os.environ.get("MDNICE_TOKEN")
    if env_token:
        return normalize_token(env_token)
    if args.agent_browser_session:
        token = token_from_agent_browser(args.agent_browser_session)
        if token:
            return normalize_token(token)
    raise RuntimeError(
        "Missing Markdown Nice token. Pass --token, --token-file, set MDNICE_TOKEN, "
        "or pass --agent-browser-session after logging in with agent-browser."
    )


def token_from_agent_browser(session_name: str) -> str | None:
    script = r"""(() => {
  const token = localStorage.getItem("token");
  return token ? { ok: true, token } : { ok: false };
})()"""
    completed = subprocess.run(
        ["agent-browser", "--session-name", session_name, "eval", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        # agent-browser versions may print JS objects; avoid leaking content and
        # only handle the normal JSON output path.
        return None
    if isinstance(payload, dict) and payload.get("ok") and isinstance(payload.get("token"), str):
        return payload["token"]
    return None


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


def multipart_form_data(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----CodexMdniceUploadBoundary"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def upload_mdnice(file_path: Path, token: str, origin: str, endpoint: str = MDNICE_UPLOAD_URL) -> str:
    if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image type for Markdown Nice: {file_path}")
    body, content_type = multipart_form_data({"origin": origin}, "file", file_path)
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": content_type,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Markdown Nice upload failed with HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict) or not payload.get("success") or not isinstance(payload.get("data"), str):
        raise RuntimeError(f"Markdown Nice upload failed: {payload}")
    url = payload["data"].strip()
    if not url.startswith("https://"):
        raise RuntimeError(f"Markdown Nice returned a non-HTTPS URL: {url}")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch upload Zhihu article images to Markdown Nice.")
    parser.add_argument("--template", type=Path, required=True, help="zhihu-image-map.template.json")
    parser.add_argument("--output", type=Path, required=True, help="Output zhihu-image-map.json")
    parser.add_argument("--token", help="Markdown Nice JWT, with or without Bearer prefix")
    parser.add_argument("--token-file", type=Path, help="File containing Markdown Nice JWT")
    parser.add_argument("--agent-browser-session", help="Read token from an already logged-in agent-browser session")
    parser.add_argument("--origin", default="codex-format-platform-article", help="Upload origin form field")
    parser.add_argument("--endpoint", default=MDNICE_UPLOAD_URL, help="Markdown Nice upload endpoint")
    parser.add_argument("--reuse-existing", action="store_true", help="Keep URLs already present in the template")
    args = parser.parse_args(argv)

    try:
        token = load_token(args)
        template = load_template(args.template)
        mapping: dict[str, str] = {}
        for index, (key, existing_url) in enumerate(template.items(), start=1):
            if args.reuse_existing and existing_url.startswith("https://"):
                mapping[key] = existing_url
                continue
            local_image = resolve_local_image(args.template, key)
            print(f"[{index}/{len(template)}] Upload {local_image.name}", file=sys.stderr)
            mapping[key] = upload_mdnice(local_image, token, args.origin, endpoint=args.endpoint)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "images": len(mapping)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
