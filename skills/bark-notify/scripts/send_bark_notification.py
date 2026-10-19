#!/usr/bin/env python3
"""
Bark Push Notification Sender
==============================
Supports all Bark API features: title, subtitle, body, markdown, sound, icon,
group, level, volume, badge, call, url, copy, autoCopy, isArchive, action,
id, delete, image, and AES encryption (CBC/ECB/GCM).

Configuration fallback hierarchy:
  1. Local skill directory (.env)
  2. Global skill directory (~/.agents/skills/bark-notify/.env)
  3. Environment variables (BARK_KEY, BARK_BASE_URL, etc.)

No external dependencies — uses only Python 3 stdlib.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import error, parse, request


SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_ENV_PATH = SKILL_DIR / ".env"
GLOBAL_ENV_PATH = Path.home() / ".agents" / "skills" / "bark-notify" / ".env"
ENV_EXAMPLE_PATH = SKILL_DIR / ".env.example"


# ---------------------------------------------------------------------------
# .env loader (with multi-path fallback)
# ---------------------------------------------------------------------------

def _load_env_file(env_path: Path) -> dict:
    """Parse a simple .env file into a dict. Supports # comments and quotes."""
    env = {}
    if not env_path.is_file():
        return env
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            env[key] = value
    except Exception:
        pass
    return env


def _resolve_env() -> tuple[dict, Optional[Path]]:
    """Load config from local .env, then fallback to global ~/.agents/.../.env."""
    if LOCAL_ENV_PATH.is_file():
        return _load_env_file(LOCAL_ENV_PATH), LOCAL_ENV_PATH
    if GLOBAL_ENV_PATH.is_file():
        return _load_env_file(GLOBAL_ENV_PATH), GLOBAL_ENV_PATH
    return {}, None


ENV, ACTIVE_ENV_PATH = _resolve_env()


def _cfg(key: str, default: str = "") -> str:
    """Read config: .env first, then environment variable, then default."""
    return ENV.get(key, os.environ.get(key, default))


def _check_config() -> bool:
    """
    Verify that configuration is available (either via .env or env vars).
    Print a helpful setup guide if missing.
    """
    if not _cfg("BARK_KEY"):
        sys.stderr.write(
            "\n"
            "  ╭─────────────────────────────────────────────╮\n"
            "  │  Bark Notify — Configuration Required       │\n"
            "  ╰─────────────────────────────────────────────╯\n"
            "\n"
            "  Missing BARK_KEY. Run setup with your Bark URL:\n"
            "\n"
            f'    python3 {SKILL_DIR}/scripts/setup.py "YOUR_BARK_URL" --force\n'
            "\n"
            "  Or set BARK_KEY in environment variables / .env\n\n"
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Project name detection (from AGENTS.md or folder)
# ---------------------------------------------------------------------------

def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1].strip()
    return value


def _extract_project_name(text: str) -> Optional[str]:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                for line in lines[1:idx]:
                    m = re.match(
                        r"\s*(project_name|project|name|title)\s*:\s*(.+)\s*$",
                        line, re.IGNORECASE,
                    )
                    if m:
                        return _strip_quotes(m.group(2))
                break
    patterns = [
        r"^\s*Project\s*Name\s*[:：]\s*(.+?)\s*$",
        r"^\s*Project\s*[:：]\s*(.+?)\s*$",
        r"^\s*项目名称\s*[:：]\s*(.+?)\s*$",
        r"^\s*项目名\s*[:：]\s*(.+?)\s*$",
    ]
    for line in lines:
        for pat in patterns:
            m = re.match(pat, line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return None


def _find_agents_file(start: Path) -> Optional[Path]:
    for candidate_root in [start] + list(start.parents):
        candidate = candidate_root / "AGENTS.md"
        if candidate.is_file():
            return candidate
    return None


def _get_project_name(cwd: Path) -> str:
    agents_path = _find_agents_file(cwd)
    if not agents_path:
        return cwd.name
    try:
        text = agents_path.read_text(encoding="utf-8", errors="ignore")
        extracted = _extract_project_name(text)
        return extracted if extracted else agents_path.parent.name
    except Exception:
        return cwd.name


# ---------------------------------------------------------------------------
# Encryption support (AES-128/192/256, CBC/ECB/GCM)
# ---------------------------------------------------------------------------

def _try_python_encrypt(plaintext: bytes, key: bytes, iv: Optional[bytes],
                         mode: str) -> Optional[str]:
    """Try encrypting with PyCryptodome if available."""
    try:
        from Crypto.Cipher import AES  # type: ignore
        from Crypto.Util.Padding import pad  # type: ignore
    except ImportError:
        return None

    if mode == "CBC":
        cipher = AES.new(key, AES.MODE_CBC, iv)
        ct = cipher.encrypt(pad(plaintext, AES.block_size))
    elif mode == "ECB":
        cipher = AES.new(key, AES.MODE_ECB)
        ct = cipher.encrypt(pad(plaintext, AES.block_size))
    elif mode == "GCM":
        cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        ct = ct + tag
    else:
        return None
    return base64.b64encode(ct).decode("utf-8")


def _try_openssl_encrypt(plaintext: bytes, key: bytes, iv: Optional[bytes],
                          mode: str, algo: str) -> Optional[str]:
    """Fallback: use openssl CLI."""
    import subprocess
    mode_lower = mode.lower()
    cipher_name = f"{algo.lower()}-{mode_lower}"
    cmd = ["openssl", "enc", f"-{cipher_name}", "-base64", "-A",
           "-K", key.hex(), "-nosalt"]
    if iv and mode_lower != "ecb":
        cmd += ["-iv", iv.hex()]
    try:
        result = subprocess.run(cmd, input=plaintext, capture_output=True, check=True)
        return result.stdout.decode("utf-8").strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def encrypt_payload(payload: dict) -> Optional[dict]:
    """Encrypt the payload JSON if encryption is configured."""
    algo = _cfg("BARK_ENCRYPT_ALGORITHM", "").upper()
    mode = _cfg("BARK_ENCRYPT_MODE", "").upper() or "CBC"
    key_str = _cfg("BARK_ENCRYPT_KEY", "")
    iv_str = _cfg("BARK_ENCRYPT_IV", "")

    if not algo or not key_str:
        sys.stderr.write(
            "Encryption not configured. Set BARK_ENCRYPT_ALGORITHM and BARK_ENCRYPT_KEY in .env.\n"
        )
        return None

    key = key_str.encode("utf-8")
    iv = iv_str.encode("utf-8") if iv_str else None

    expected = {"AES128": 16, "AES192": 24, "AES256": 32}
    if algo not in expected:
        sys.stderr.write(f"Unsupported algorithm: {algo}\n")
        return None
    if len(key) != expected[algo]:
        sys.stderr.write(f"Key length mismatch: {algo} requires {expected[algo]} bytes, got {len(key)}\n")
        return None

    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ct = _try_python_encrypt(plaintext, key, iv, mode)
    if ct is None:
        ct = _try_openssl_encrypt(plaintext, key, iv, mode, algo)
    if ct is None:
        sys.stderr.write("Encryption failed: neither pycryptodome nor openssl available.\n")
        return None

    result = {"ciphertext": ct}
    if iv_str and mode != "ECB":
        result["iv"] = iv_str
    return result


# ---------------------------------------------------------------------------
# Bark API sender with retry & dry-run redaction
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    "success": "✅",
    "failed": "❌",
    "partial": "⚠️",
    "blocked": "🚫",
    "info": "ℹ️",
    "warning": "⚠️",
}

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def send_bark(params: dict, timeout: float = 10.0, dry_run: bool = False, max_retries: int = 3) -> int:
    """Send a Bark push notification with exponential backoff for transient failures."""
    bark_key = _cfg("BARK_KEY")
    base_url = _cfg("BARK_BASE_URL", "https://api.day.app").rstrip("/")

    if not bark_key:
        sys.stderr.write("Missing BARK_KEY in configuration\n")
        return 1

    url = f"{base_url}/{parse.quote(bark_key)}"

    if dry_run:
        print(f"POST {base_url}/<redacted>")
        print(json.dumps(params, indent=2, ensure_ascii=False))
        return 0

    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    body = ""
    last_err: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        req = request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore").strip()
            # If server returned an HTML error page (e.g. nginx 502 bad gateway)
            if body.lstrip()[:15].lower().startswith(("<!doctype", "<html")) and attempt < max_retries:
                time.sleep(2 ** (attempt - 1))
                continue
            last_err = None
            break
        except error.HTTPError as exc:
            last_err = exc
            body = exc.read().decode("utf-8", errors="ignore").strip()
            if exc.code in RETRYABLE_STATUS and attempt < max_retries:
                time.sleep(2 ** (attempt - 1))
                continue
            break
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                time.sleep(2 ** (attempt - 1))
                continue
            break

    if last_err is not None:
        if isinstance(last_err, error.HTTPError):
            sys.stderr.write(f"HTTP {last_err.code}: {last_err.reason}\n")
            if body:
                snippet = body.replace("\n", " ")[:240]
                sys.stderr.write(f"Response: {snippet}\n")
        else:
            sys.stderr.write(f"Failed to send Bark notification: {last_err}\n")
        return 1

    if body:
        try:
            parsed_res = json.loads(body)
            code = parsed_res.get("code")
            if code not in (None, 200):
                sys.stderr.write(f"Bark rejected notification: {body}\n")
                return 1
        except json.JSONDecodeError:
            pass
        print(body)
    return 0


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send Bark push notifications with full API support.")
    p.add_argument("--task-title", help="Short task title.")
    p.add_argument("--status", help="Execution status (success/failed/partial/blocked).")
    p.add_argument("--summary", help="Result summary.")
    p.add_argument("--project-name", help="Override project name.")

    p.add_argument("--title", help="Push title.")
    p.add_argument("--subtitle", help="Push subtitle.")
    p.add_argument("--body", help="Push body content.")
    p.add_argument("--markdown", help="Push body as Markdown (overrides --body).")
    p.add_argument("--sound", help="Notification sound name.")
    p.add_argument("--icon", help="Custom notification icon URL.")
    p.add_argument("--image", help="Push image URL.")
    p.add_argument("--group", help="Notification group name.")
    p.add_argument("--url", help="URL to open when notification is tapped.")
    p.add_argument("--copy", help="Text to copy when notification is long-pressed.")
    p.add_argument("--auto-copy", dest="autoCopy", action="store_true", help="Auto-copy push content.")
    p.add_argument("--level", choices=["active", "timeSensitive", "passive", "critical"], help="Interruption level.")
    p.add_argument("--volume", type=int, choices=range(0, 11), help="Critical alert volume (0-10).", metavar="0-10")
    p.add_argument("--badge", type=int, help="App badge number.")
    p.add_argument("--call", action="store_true", help="Repeat ringtone for 30 seconds.")
    p.add_argument("--is-archive", dest="isArchive", action="store_true", help="Force archive the notification.")
    p.add_argument("--action", help="Action on tap (e.g. 'alert' or 'none').")
    p.add_argument("--notify-id", dest="id", help="Notification ID for updates.")
    p.add_argument("--delete", action="store_true", help="Delete notification by --notify-id.")

    p.add_argument("--encrypt", action="store_true", help="Encrypt payload with AES.")
    p.add_argument("--timeout", type=float, default=10.0, help="HTTP request timeout in seconds.")
    p.add_argument("--retries", type=int, default=3, help="Max retry attempts for transient errors.")
    p.add_argument("--dry-run", action="store_true", help="Preview notification payload without sending.")
    return p.parse_args()


def main() -> int:
    if "--setup" in sys.argv:
        import subprocess
        setup_script = SKILL_DIR / "scripts" / "setup.py"
        setup_args = [a for a in sys.argv[1:] if a != "--setup"]
        return subprocess.call([sys.executable, str(setup_script)] + setup_args)

    args = _parse_args()

    if not _check_config():
        return 1

    if args.task_title:
        machine_name = _cfg("BARK_MACHINE_NAME", "Unknown")
        project_name = args.project_name or _get_project_name(Path.cwd())
        status = (args.status or "info").strip()
        summary = (args.summary or "").strip()
        emoji = STATUS_EMOJI.get(status, "📌")

        params = {
            "title": f"{emoji} {args.task_title.strip()}",
            "body": "\n".join(filter(None, [
                f"Device: {machine_name}",
                f"Project: {project_name}",
                f"Status: {status}",
                f"Summary: {summary}" if summary else None,
            ])),
            "group": f"agent-{project_name}",
        }
    elif args.title or args.body or args.markdown:
        params = {}
        for key in ("title", "subtitle", "body", "markdown", "sound", "icon",
                     "image", "group", "url", "copy", "level", "action", "id"):
            val = getattr(args, key, None)
            if val is not None:
                params[key] = val
        if args.autoCopy:
            params["autoCopy"] = "1"
        if args.call:
            params["call"] = "1"
        if args.isArchive:
            params["isArchive"] = "1"
        if args.delete:
            params["delete"] = "1"
        if args.volume is not None:
            params["volume"] = args.volume
        if args.badge is not None:
            params["badge"] = args.badge
    else:
        sys.stderr.write("Error: provide either --task-title (task mode) or --title/--body (direct mode).\n")
        return 1

    if args.encrypt:
        encrypted = encrypt_payload(params)
        if encrypted is None:
            return 1
        params = encrypted

    return send_bark(params, timeout=args.timeout, dry_run=args.dry_run, max_retries=args.retries)


if __name__ == "__main__":
    raise SystemExit(main())
