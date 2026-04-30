#!/usr/bin/env python3
"""
Upload a local file to Notion via the File Upload API and attach it as a block to a page.

Supports: images (png/jpg/gif/webp/svg), PDFs, videos (mp4/mov/webm), audio (mp3/wav/ogg), and generic files.

Usage:
    python upload_to_notion.py <file_path> <page_id> [--block-type auto] [--caption "..."]

Requirements:
    - NOTION_API_KEY environment variable
    - requests library (pip install requests)
"""

import argparse
import json
import math
import mimetypes
import os
import sys
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _session() -> requests.Session:
    """Create a requests session with retry and backoff."""
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# Load .env from skill root directory (parent of scripts/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.is_file():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

NOTION_BASE_URL = "https://api.notion.com"
NOTION_VERSION = "2022-06-28"

# Map file extensions to Notion block types
BLOCK_TYPE_MAP = {
    # Images
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".bmp": "image", ".tiff": "image", ".ico": "image",
    # PDFs
    ".pdf": "pdf",
    # Videos
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".avi": "video", ".mkv": "video",
    # Audio
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio",
    ".flac": "audio", ".m4a": "audio",
}

MAX_SINGLE_PART_SIZE = 20 * 1024 * 1024  # 20MB
PART_SIZE = 10 * 1024 * 1024              # 10MB per part for multi-part
MAX_TOTAL_SIZE = 5 * 1024 * 1024 * 1024   # 5GB max


def get_headers(api_key: str, content_type: str = "application/json") -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def detect_block_type(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    return BLOCK_TYPE_MAP.get(ext, "file")


def detect_mime_type(filepath: str) -> str:
    mime, _ = mimetypes.guess_type(filepath)
    return mime or "application/octet-stream"


def create_file_upload(api_key: str, filename: str, content_type: str, file_size: int) -> dict:
    """Step 1: Create a file upload object (single-part or multi-part)."""
    url = f"{NOTION_BASE_URL}/v1/file_uploads"

    if file_size <= MAX_SINGLE_PART_SIZE:
        payload = {
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
            "content_length": file_size,
        }
    else:
        number_of_parts = math.ceil(file_size / PART_SIZE)
        payload = {
            "mode": "multi_part",
            "filename": filename,
            "content_type": content_type,
            "number_of_parts": number_of_parts,
        }

    resp = _session().post(url, headers=get_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_file_content_single(api_key: str, upload_url: str, filepath: str, filename: str, content_type: str) -> dict:
    """Upload file content in a single request (≤ 20MB)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
    }
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, content_type)}
        resp = _session().post(upload_url, headers=headers, files=files, timeout=120)
    resp.raise_for_status()
    return resp.json()


def send_file_content_multipart(api_key: str, file_upload_id: str, filepath: str, filename: str, content_type: str) -> None:
    """Upload file content in multiple parts (> 20MB)."""
    file_size = os.path.getsize(filepath)
    number_of_parts = math.ceil(file_size / PART_SIZE)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
    }
    url = f"{NOTION_BASE_URL}/v1/file_uploads/{file_upload_id}/send"

    with open(filepath, "rb") as f:
        for part_num in range(1, number_of_parts + 1):
            chunk = f.read(PART_SIZE)
            if not chunk:
                break
            files = {
                "file": (filename, chunk, content_type),
                "part_number": (None, str(part_num)),
            }
            print(f"  Sending part {part_num}/{number_of_parts} ({len(chunk)} bytes)...")
            resp = _session().post(url, headers=headers, files=files, timeout=300)
            resp.raise_for_status()


def complete_file_upload(api_key: str, file_upload_id: str) -> dict:
    """Complete a multi-part file upload."""
    url = f"{NOTION_BASE_URL}/v1/file_uploads/{file_upload_id}/complete"
    resp = _session().post(url, headers=get_headers(api_key), timeout=30)
    resp.raise_for_status()
    return resp.json()


def attach_to_page(api_key: str, page_id: str, file_upload_id: str, block_type: str, caption: str = "") -> dict:
    """Step 3: Attach the uploaded file as a block to the target page."""
    url = f"{NOTION_BASE_URL}/v1/blocks/{page_id}/children"

    caption_array = []
    if caption:
        caption_array = [{"type": "text", "text": {"content": caption}}]

    block = {
        "type": block_type,
        block_type: {
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
            "caption": caption_array,
        },
    }

    # "file" block type uses a different caption structure (no caption field)
    if block_type == "file":
        block = {
            "type": "file",
            "file": {
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
            },
        }
        if caption:
            block["file"]["caption"] = caption_array

    payload = {"children": [block]}
    resp = _session().patch(url, headers=get_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upload_file_to_notion(filepath: str, page_id: str, block_type: str = "auto", caption: str = "") -> dict:
    """
    Upload a local file to Notion and attach it to the specified page.

    Args:
        filepath: Path to the local file.
        page_id: Notion page ID to attach the file to.
        block_type: Block type (image/pdf/video/audio/file/auto). "auto" detects from extension.
        caption: Optional caption text.

    Returns:
        dict with upload result info.
    """
    api_key = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN", "")
    if not api_key:
        return {"success": False, "error": "NOTION_API_KEY environment variable not set"}

    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        return {"success": False, "error": f"File not found: {filepath}"}

    file_size = os.path.getsize(filepath)
    if file_size > MAX_TOTAL_SIZE:
        return {"success": False, "error": f"File too large ({file_size} bytes). Max upload size is 5GB."}

    filename = os.path.basename(filepath)
    content_type = detect_mime_type(filepath)
    is_multipart = file_size > MAX_SINGLE_PART_SIZE

    if block_type == "auto":
        block_type = detect_block_type(filepath)

    size_mb = file_size / (1024 * 1024)
    mode_label = "multi-part" if is_multipart else "single-part"
    print(f"Uploading: {filename} ({content_type}, {size_mb:.1f} MB, {mode_label})")
    print(f"Block type: {block_type}")
    print(f"Target page: {page_id}")

    total_steps = 4 if is_multipart else 3

    # Step 1: Create file upload
    print(f"Step 1/{total_steps}: Creating file upload ({mode_label})...")
    upload_obj = create_file_upload(api_key, filename, content_type, file_size)
    file_upload_id = upload_obj["id"]
    print(f"  File upload ID: {file_upload_id}")

    # Step 2: Send file content
    if is_multipart:
        num_parts = math.ceil(file_size / PART_SIZE)
        print(f"Step 2/{total_steps}: Sending file content in {num_parts} parts...")
        send_file_content_multipart(api_key, file_upload_id, filepath, filename, content_type)
        print("  All parts sent.")

        # Step 3: Complete multi-part upload
        print(f"Step 3/{total_steps}: Completing multi-part upload...")
        complete_file_upload(api_key, file_upload_id)
        print("  Upload completed.")
    else:
        upload_url = upload_obj.get("upload_url", f"{NOTION_BASE_URL}/v1/file_uploads/{file_upload_id}/send")
        print(f"Step 2/{total_steps}: Sending file content...")
        send_file_content_single(api_key, upload_url, filepath, filename, content_type)
        print("  File content sent.")

    # Final step: Attach to page
    print(f"Step {total_steps}/{total_steps}: Attaching to page...")
    result = attach_to_page(api_key, page_id, file_upload_id, block_type, caption)
    print("  Done!")

    return {
        "success": True,
        "file_upload_id": file_upload_id,
        "block_type": block_type,
        "filename": filename,
        "page_id": page_id,
        "block_result": result,
    }


def main():
    parser = argparse.ArgumentParser(description="Upload a file to Notion and attach it to a page")
    parser.add_argument("file", help="Path to the local file")
    parser.add_argument("page_id", help="Notion page ID to attach the file to")
    parser.add_argument("--block-type", default="auto",
                        choices=["auto", "image", "pdf", "video", "audio", "file"],
                        help="Block type (default: auto-detect from extension)")
    parser.add_argument("--caption", default="", help="Optional caption text")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format")

    args = parser.parse_args()

    try:
        result = upload_file_to_notion(args.file, args.page_id, args.block_type, args.caption)
    except requests.HTTPError as e:
        result = {"success": False, "error": str(e), "response": e.response.text if e.response else ""}

    if args.output == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["success"]:
            print(f"\n✅ Successfully uploaded '{result['filename']}' as {result['block_type']} block to page {result['page_id']}")
        else:
            print(f"\n❌ Upload failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
