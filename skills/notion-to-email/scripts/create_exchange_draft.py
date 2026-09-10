#!/usr/bin/env python3
"""Create an Exchange draft from a generated .eml via exchange-cli.

`draft create` accepts HTML (`--body-type html`) but has no `--body-file`
or `--attach`. Inline CID images as data URIs, then pass the HTML as
`--body`. Never send the draft.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path


def _part_bytes(part) -> bytes:
    payload = part.get_payload(decode=True)
    if payload is None:
        raise ValueError(f"empty payload for {part.get_content_type()}")
    return payload


def _content_id(part) -> str | None:
    cid = part.get("Content-ID")
    if not cid:
        return None
    return cid.strip().strip("<>")


def eml_to_draft_payload(eml_path: str | Path) -> dict:
    """Parse an .eml into exchange-cli draft create fields.

    Returns subject, to/cc address lists, and HTML with cid: images
    rewritten to data URIs.
    """
    raw = Path(eml_path).read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    html = None
    images = {}
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and html is None:
            html = part.get_content()
            continue
        cid = _content_id(part)
        if cid and ctype.startswith("image/"):
            images[cid] = (ctype, _part_bytes(part))

    if not html:
        raise ValueError(f"no text/html part in {eml_path}")

    for cid, (ctype, data) in images.items():
        b64 = base64.b64encode(data).decode("ascii")
        html = html.replace(f"cid:{cid}", f"data:{ctype};base64,{b64}")

    to_addrs = [addr for _, addr in getaddresses([msg.get("To") or ""]) if addr]
    cc_addrs = [addr for _, addr in getaddresses([msg.get("Cc") or ""]) if addr]
    subject = msg.get("Subject") or ""

    return {
        "subject": str(subject),
        "to": to_addrs,
        "cc": cc_addrs,
        "html": html,
    }


def create_exchange_draft(payload: dict) -> dict:
    if not payload.get("to"):
        raise ValueError("draft needs at least one To address")
    if not payload.get("subject"):
        raise ValueError("draft needs a subject")

    cmd = [
        "exchange-cli",
        "draft",
        "create",
        "--to",
        ",".join(payload["to"]),
    ]
    if payload.get("cc"):
        cmd += ["--cc", ",".join(payload["cc"])]
    cmd += [
        "--subject",
        payload["subject"],
        "--body-type",
        "html",
        "--body",
        payload["html"],
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"exchange-cli draft create failed ({result.returncode}): {err}")

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"exchange-cli returned non-JSON: {result.stdout[:500]}") from exc
    if not parsed.get("ok"):
        raise RuntimeError(f"exchange-cli draft create error: {parsed}")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an Exchange draft from a generated .eml")
    parser.add_argument("eml_file", help="Path to the .eml produced by render_email.py --eml")
    args = parser.parse_args()

    payload = eml_to_draft_payload(args.eml_file)
    created = create_exchange_draft(payload)
    data = created.get("data") or {}
    print(f"✅ Exchange draft created: {data.get('subject') or payload['subject']}")
    if data.get("id"):
        print(f"   id: {data['id']}")
    print("Open Outlook Drafts to review, then send from there. Do not use draft send unless asked.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
