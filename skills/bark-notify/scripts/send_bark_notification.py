#!/usr/bin/env python3
"""
Bark Push Notification Sender
==============================
Supports all Bark API features: title, subtitle, body, markdown, sound, icon,
group, level, volume, badge, call, url, copy, autoCopy, isArchive, action,
id, delete, image, and AES encryption (CBC/ECB/GCM).

Configuration is read from .env file in the skill directory.
No external dependencies — uses only Python 3 stdlib.

Repository: https://github.com/backtomyfuture/bark-notify
License:    MIT
"""
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib import error, parse, request


SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SKILL_DIR / ".env"
ENV_EXAMPLE_PATH = SKILL_DIR / ".env.example"


# ---------------------------------------------------------------------------
# .env loader (no external dependency)
# ---------------------------------------------------------------------------

def _load_env(env_path: Path) -> dict:
    """Parse a simple .env file into a dict. Supports # comments and quotes."""
    env = {}
    if not env_path.is_file():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


ENV = _load_env(ENV_PATH)


def _cfg(key: str, default: str = "") -> str:
    """Read config: .env first, then env var, then default."""
    return ENV.get(key, os.environ.get(key, default))


def _check_config() -> bool:
    """
    Verify that .env exists and has the required keys.
    Print a helpful setup guide if not.
    """
    if not ENV_PATH.is_file():
        sys.stderr.write(
            "\n"
            "  ╭─────────────────────────────────────────────╮\n"
            "  │  Bark Notify — Configuration Required       │\n"
            "  ╰─────────────────────────────────────────────╯\n"
            "\n"
            "  No .env file found. Run the setup script:\n"
            "\n"
            f'    python3 {SKILL_DIR}/scripts/setup.py "YOUR_BARK_URL"\n'
            "\n"
            "  Or copy the example and edit manually:\n"
            "\n"
            f"    cp {ENV_EXAMPLE_PATH} {ENV_PATH}\n"
            f"    # Then edit {ENV_PATH}\n"
            "\n"
        )
        return False

    if not _cfg("BARK_KEY"):
        sys.stderr.write(
            "  ❌ BARK_KEY is empty in .env\n"
            "  Open the Bark app, copy your URL, and run:\n"
            f'    python3 {SKILL_DIR}/scripts/setup.py "YOUR_BARK_URL"\n\n'
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Project name detection (from AGENTS.md)
# ---------------------------------------------------------------------------

def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1].strip()
    return value


def _extract_project_name(text: str) -> Optional[str]:
    lines = text.splitlines()
    # YAML frontmatter
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
    # Plain text patterns
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
    text = agents_path.read_text(encoding="utf-8", errors="ignore")
    extracted = _extract_project_name(text)
    return extracted if extracted else agents_path.parent.name


# ---------------------------------------------------------------------------
# Encryption support  (AES-128/192/256, CBC/ECB/GCM, PKCS7 padding)
# Uses only Python stdlib — no pycryptodome needed.
# Falls back to openssl CLI which is available on macOS/Linux.
# ---------------------------------------------------------------------------

def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


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
        ct = ct + tag  # combined mode
    else:
        return None
    return base64.b64encode(ct).decode("utf-8")


def _try_openssl_encrypt(plaintext: bytes, key: bytes, iv: Optional[bytes],
                          mode: str, algo: str) -> Optional[str]:
    """Fallback: use openssl CLI."""
    import subprocess
    mode_lower = mode.lower()
    if algo == "AES128":
        cipher_name = f"aes-128-{mode_lower}"
    elif algo == "AES192":
        cipher_name = f"aes-192-{mode_lower}"
    else:
        cipher_name = f"aes-256-{mode_lower}"

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
    """
    If encryption is configured, encrypt the payload JSON and return
    {"ciphertext": "...", "iv": "..."} dict. Otherwise return None.
    """
    algo = _cfg("BARK_ENCRYPT_ALGORITHM", "").upper()
    mode = _cfg("BARK_ENCRYPT_MODE", "").upper()
    key_str = _cfg("BARK_ENCRYPT_KEY", "")
    iv_str = _cfg("BARK_ENCRYPT_IV", "")

    if not algo or not key_str:
        sys.stderr.write(
            "Encryption not configured. Set these in .env:\n"
            "  BARK_ENCRYPT_ALGORITHM=AES256\n"
            "  BARK_ENCRYPT_MODE=CBC\n"
            "  BARK_ENCRYPT_KEY=your-32-byte-key-here!!!\n"
            "  BARK_ENCRYPT_IV=your-16-byte-iv!!\n"
        )
        return None

    mode = mode or "CBC"
    key = key_str.encode("utf-8")
    iv = iv_str.encode("utf-8") if iv_str else None

    # Validate key length
    expected = {"AES128": 16, "AES192": 24, "AES256": 32}
    if algo not in expected:
        sys.stderr.write(f"Unsupported algorithm: {algo}\n")
        return None
    if len(key) != expected[algo]:
        sys.stderr.write(
            f"Key length mismatch: {algo} requires {expected[algo]} bytes, "
            f"got {len(key)}\n"
        )
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
# Bark API sender
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    "success": "✅",
    "failed": "❌",
    "partial": "⚠️",
    "blocked": "🚫",
    "info": "ℹ️",
    "warning": "⚠️",
}


def send_bark(params: dict, timeout: float = 10.0, dry_run: bool = False) -> int:
    """
    Send a Bark push notification.

    params: dict of Bark API parameters (title, body, sound, icon, group,
            level, badge, url, copy, autoCopy, isArchive, call, volume,
            action, id, delete, image, markdown, ciphertext, iv, ...)
    """
    bark_key = _cfg("BARK_KEY")
    base_url = _cfg("BARK_BASE_URL", "https://api.day.app")

    if not bark_key:
        sys.stderr.write("Missing BARK_KEY in .env\n")
        return 1

    url = f"{base_url.rstrip('/')}/{parse.quote(bark_key)}"

    if dry_run:
        print(f"POST {url}")
        print(json.dumps(params, indent=2, ensure_ascii=False))
        return 0

    # Use JSON POST for best compatibility
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore").strip()
    except error.HTTPError as exc:
        sys.stderr.write(f"HTTP {exc.code}: {exc.reason}\n")
        sys.stderr.write(exc.read().decode("utf-8", errors="ignore"))
        return 1
    except Exception as exc:
        sys.stderr.write(f"Failed to send Bark notification: {exc}\n")
        return 1

    if body:
        print(body)
    return 0


# ---------------------------------------------------------------------------
# CLI: task completion notification (backward-compatible)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send Bark push notifications with full API support."
    )
    # --- Task completion mode (original) ---
    p.add_argument("--task-title", help="Short task title.")
    p.add_argument("--status", help="Execution status (success/failed/partial/blocked).")
    p.add_argument("--summary", help="Result summary.")
    p.add_argument("--project-name", help="Override project name.")

    # --- Direct Bark API parameters ---
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
    p.add_argument("--auto-copy", dest="autoCopy", action="store_true",
                   help="Auto-copy push content.")
    p.add_argument("--level", choices=["active", "timeSensitive", "passive", "critical"],
                   help="Interruption level.")
    p.add_argument("--volume", type=int, choices=range(0, 11),
                   help="Critical alert volume (0-10).", metavar="0-10")
    p.add_argument("--badge", type=int, help="App badge number.")
    p.add_argument("--call", action="store_true",
                   help="Repeat ringtone for 30 seconds.")
    p.add_argument("--is-archive", dest="isArchive", action="store_true",
                   help="Force archive the notification.")
    p.add_argument("--action", help="Action on tap (e.g. 'alert' or 'none').")
    p.add_argument("--notify-id", dest="id", help="Notification ID for updates.")
    p.add_argument("--delete", action="store_true",
                   help="Delete notification by --notify-id.")

    # --- Other ---
    p.add_argument("--encrypt", action="store_true",
                   help="Encrypt the payload (requires encryption config in .env).")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    # Quick --setup shortcut: delegate to setup.py
    if "--setup" in sys.argv:
        import subprocess
        setup_script = SKILL_DIR / "scripts" / "setup.py"
        setup_args = [a for a in sys.argv[1:] if a != "--setup"]
        return subprocess.call([sys.executable, str(setup_script)] + setup_args)

    args = _parse_args()

    # Verify configuration before doing anything
    if not _check_config():
        return 1

    # Determine mode: task-completion vs direct API
    if args.task_title:
        # --- Task completion mode ---
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
        # --- Direct API mode ---
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
        sys.stderr.write(
            "Error: provide either --task-title (task mode) or "
            "--title/--body (direct mode).\n"
        )
        return 1

    # Encryption
    if args.encrypt:
        encrypted = encrypt_payload(params)
        if encrypted is None:
            return 1
        params = encrypted

    return send_bark(params, timeout=args.timeout, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
