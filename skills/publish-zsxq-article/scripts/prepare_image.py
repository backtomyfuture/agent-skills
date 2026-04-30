#!/usr/bin/env python3
"""
Prepare an image for injection into Zsxq article editor via synthetic ClipboardEvent.

Reads an image file, base64-encodes it, and writes a self-contained JS file
that can be eval'd by agent-browser to paste the image into the Milkdown
ProseMirror editor using a synthetic binary ClipboardEvent.

This bypasses system clipboard entirely — no headed mode or OS permissions needed.

Usage:
    python3 prepare_image.py /path/to/image.png
    python3 prepare_image.py /path/to/image.png --output /tmp/zsxq_paste_image.js
    python3 prepare_image.py /path/to/image.png --max-size 1500

Then run (marker deletion is a SEPARATE step — see SKILL.md Step 6):
    agent-browser --session-name zsxq eval "$(cat /tmp/zsxq_paste_image.js)"

Output JSON from eval: { ok, size }
"""

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path

# Max base64 size to embed inline (5MB decoded ~ 6.7MB base64)
MAX_INLINE_SIZE = 5 * 1024 * 1024

# Supported image formats
SUPPORTED_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'}


def get_mime_type(ext: str) -> str:
    """Get MIME type from file extension."""
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
    }
    return mime_map.get(ext.lower(), 'image/png')


def compress_if_needed(image_path: str, max_size: int = 2000) -> bytes:
    """Read image, compress/resize if too large, return bytes."""
    file_size = os.path.getsize(image_path)

    # If small enough and is PNG/JPEG, just read raw
    if file_size <= MAX_INLINE_SIZE:
        with open(image_path, 'rb') as f:
            return f.read()

    # Compress with Pillow
    try:
        from PIL import Image
        img = Image.open(image_path)
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        compressed = buf.getvalue()
        print(f"Compressed: {file_size} -> {len(compressed)} bytes", file=sys.stderr)
        return compressed
    except ImportError:
        print("WARNING: Pillow not installed, using raw image (may be large)", file=sys.stderr)
        with open(image_path, 'rb') as f:
            return f.read()


def generate_image_paste_js(b64_data: str, filename: str, mime_type: str,
                            marker: str = None) -> str:
    """Generate JS IIFE that ONLY pastes the image via synthetic ClipboardEvent.

    Marker deletion is handled separately (see SKILL.md Step 6) — this
    separation is critical because ProseMirror needs time to sync its internal
    selection with the DOM between marker deletion and image paste. Combining
    them in a single eval causes images to land at the wrong position.
    """
    return f"""(() => {{
  const editor = document.querySelector('.ProseMirror');
  if (!editor) return {{ ok: false, error: 'ProseMirror editor not found' }};

  editor.focus();

  const b64 = '{b64_data}';
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const file = new File([bytes], '{filename}', {{ type: '{mime_type}' }});
  const dt = new DataTransfer();
  dt.items.add(file);

  const ev = new ClipboardEvent('paste', {{
    bubbles: true,
    cancelable: true,
    clipboardData: dt
  }});
  editor.dispatchEvent(ev);

  return {{ ok: true, size: file.size }};
}})()"""


def main():
    parser = argparse.ArgumentParser(description='Prepare image for Zsxq editor injection')
    parser.add_argument('path', help='Path to image file')
    parser.add_argument('--output', '-o', default='/tmp/zsxq_paste_image.js',
                        help='Output JS file path (default: /tmp/zsxq_paste_image.js)')
    parser.add_argument('--max-size', type=int, default=2000,
                        help='Max image dimension for compression (default: 2000)')
    args = parser.parse_args()

    # Validate
    image_path = Path(args.path)
    if not image_path.exists():
        print(f"Error: Image not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    ext = image_path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        print(f"Error: Unsupported image format: {ext}", file=sys.stderr)
        print(f"Supported: {', '.join(sorted(SUPPORTED_EXTS))}", file=sys.stderr)
        sys.exit(1)

    # Read and possibly compress
    image_data = compress_if_needed(str(image_path), args.max_size)
    b64_data = base64.b64encode(image_data).decode('ascii')

    if len(image_data) > MAX_INLINE_SIZE:
        print(f"WARNING: Image is {len(image_data)} bytes after compression. "
              f"Very large base64 may cause issues.", file=sys.stderr)

    # Determine mime type (use JPEG if compressed, otherwise original)
    if os.path.getsize(str(image_path)) > MAX_INLINE_SIZE:
        mime_type = 'image/jpeg'  # Was compressed to JPEG
        filename = image_path.stem + '.jpg'
    else:
        mime_type = get_mime_type(ext)
        filename = image_path.name

    # Generate JS (paste only — marker deletion is separate, see SKILL.md Step 6)
    js_code = generate_image_paste_js(b64_data, filename, mime_type)

    # Write
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js_code)

    # Summary
    result = {
        'image': str(image_path),
        'size_bytes': len(image_data),
        'base64_chars': len(b64_data),
        'js_file': str(output_path),
        'note': 'Marker deletion is handled separately — see SKILL.md Step 6',
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
