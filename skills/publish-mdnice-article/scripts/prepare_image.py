#!/usr/bin/env python3
"""
Prepare an image for injection into Markdown Nice editor via synthetic ClipboardEvent.

Reads an image file, base64-encodes it, and writes a self-contained JS file
that can be eval'd by agent-browser to paste the image into Markdown Nice
using a synthetic binary ClipboardEvent.

This bypasses system clipboard entirely — no headed mode or OS permissions needed.

Usage:
    python3 prepare_image.py /path/to/image.png
    python3 prepare_image.py /path/to/image.png --output /tmp/mdnice_paste_image.js
    python3 prepare_image.py /path/to/image.png --max-size 1500

Then run (marker deletion is a SEPARATE step — see SKILL.md Step 6):
    agent-browser --session-name mdnice eval "$(cat /tmp/mdnice_paste_image.js)"

Output JSON from eval: { ok, size }
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Max base64 size to embed inline (5MB decoded ~ 6.7MB base64)
MAX_INLINE_SIZE = 5 * 1024 * 1024

# Windows process command lines are limited to about 32K characters. The
# generated JS includes the base64 payload, so keep the default below that.
WINDOWS_INLINE_BASE64_CHARS = 24_000

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


def base64_char_count(byte_count: int) -> int:
    """Return the number of base64 characters needed for byte_count bytes."""
    return ((byte_count + 2) // 3) * 4


def should_compress_for_command_line(
    base64_chars: int,
    platform_name: str = os.name,
    max_inline_chars: int = WINDOWS_INLINE_BASE64_CHARS,
) -> bool:
    """Return true when inline JS is likely too large for the shell."""
    return platform_name == 'nt' and base64_chars > max_inline_chars


def compress_with_powershell(image_path: str, max_size: int = 2000) -> bytes:
    """Resize/compress an image on Windows using built-in System.Drawing."""
    fd, output_path = tempfile.mkstemp(suffix='.jpg')
    os.close(fd)
    os.unlink(output_path)

    ps_script = r'''
param(
  [string]$inputPath,
  [string]$outputPath,
  [int]$maxSize
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$quality = [int64]75
$jpegCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$params = New-Object System.Drawing.Imaging.EncoderParameters(1)
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, $quality)
$img = [System.Drawing.Image]::FromFile($inputPath)
try {
  $longest = [Math]::Max($img.Width, $img.Height)
  $scale = [Math]::Min(1.0, $maxSize / $longest)
  $targetW = [int][Math]::Max(1, [Math]::Round($img.Width * $scale))
  $targetH = [int][Math]::Max(1, [Math]::Round($img.Height * $scale))
  $bmp = New-Object System.Drawing.Bitmap($targetW, $targetH)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  try {
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($img, 0, 0, $targetW, $targetH)
    $bmp.Save($outputPath, $jpegCodec, $params)
  } finally {
    $g.Dispose()
    $bmp.Dispose()
  }
} finally {
  $img.Dispose()
}
'''
    with tempfile.NamedTemporaryFile('w', suffix='.ps1', delete=False, encoding='utf-8') as ps_file:
        ps_file.write(ps_script)
        ps_path = ps_file.name

    try:
        completed = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                ps_path,
                image_path,
                output_path,
                str(max_size),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        with open(output_path, 'rb') as f:
            compressed = f.read()
        if not compressed:
            raise RuntimeError('PowerShell compression produced an empty file')
        return compressed
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        try:
            os.unlink(ps_path)
        except OSError:
            pass


def compress_if_needed(
    image_path: str,
    max_size: int = 2000,
    max_inline_chars: int = WINDOWS_INLINE_BASE64_CHARS,
    allow_large_inline: bool = False,
) -> bytes:
    """Read image, compress/resize if too large, return bytes."""
    file_size = os.path.getsize(image_path)
    projected_base64_chars = base64_char_count(file_size)
    needs_inline_compression = should_compress_for_command_line(
        projected_base64_chars,
        max_inline_chars=max_inline_chars,
    )

    # If small enough and is PNG/JPEG, just read raw
    if file_size <= MAX_INLINE_SIZE and not needs_inline_compression:
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
        if os.name == 'nt':
            try:
                compressed = compress_with_powershell(image_path, max_size)
                print(f"Compressed with PowerShell: {file_size} -> {len(compressed)} bytes",
                      file=sys.stderr)
                return compressed
            except Exception as exc:
                print(f"WARNING: PowerShell image compression failed: {exc}", file=sys.stderr)
        if needs_inline_compression and not allow_large_inline:
            print(
                "ERROR: This image would generate a very large inline JS payload on "
                "Windows. Install Pillow (`python -m pip install Pillow`) or re-run "
                "with --allow-large-inline if you will not pass the JS through a "
                "Windows command line.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("WARNING: Pillow not installed, using raw image (may be large)", file=sys.stderr)
        with open(image_path, 'rb') as f:
            return f.read()


def generate_image_paste_js(b64_data: str, filename: str, mime_type: str,
                            marker: str = None) -> str:
    """Generate JS IIFE that ONLY pastes the image via synthetic ClipboardEvent.

    Marker deletion is handled separately (see SKILL.md) because Markdown Nice
    may re-render the editor after the marker is removed. Combining deletion
    and paste in a single eval can place images at the wrong cursor position.
    """
    return f"""(() => {{
  const editor = document.querySelector('#nice-md-editor');
  if (!editor) return {{ ok: false, error: '#nice-md-editor not found' }};

  const cmEl = editor.querySelector('.CodeMirror') || document.querySelector('.CodeMirror');
  const cm = cmEl?.CodeMirror;
  if (cm) cm.focus();
  const pasteTarget = cm?.getInputField?.()
    || cm?.getTextArea?.()
    || cm?.display?.input?.textarea
    || editor;
  pasteTarget.focus?.();

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
  const dispatchTarget = pasteTarget.dispatchEvent(ev);
  let dispatchWrapper = null;
  if (cmEl && cmEl !== pasteTarget) dispatchWrapper = cmEl.dispatchEvent(ev);

  return {{ ok: true, size: file.size, target: pasteTarget.tagName || '', dispatchTarget, dispatchWrapper }};
}})()"""


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='Prepare image for Markdown Nice editor injection')
    parser.add_argument('path', help='Path to image file')
    parser.add_argument('--output', '-o', default='/tmp/mdnice_paste_image.js',
                        help='Output JS file path (default: /tmp/mdnice_paste_image.js)')
    parser.add_argument('--max-size', type=int, default=2000,
                        help='Max image dimension for compression (default: 2000)')
    parser.add_argument('--max-inline-chars', type=int, default=WINDOWS_INLINE_BASE64_CHARS,
                        help='Max base64 chars to inline on Windows before resizing')
    parser.add_argument('--allow-large-inline', action='store_true',
                        help='Allow oversized inline JS even when it may exceed shell limits')
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
    original_size = os.path.getsize(str(image_path))
    image_data = compress_if_needed(
        str(image_path),
        args.max_size,
        args.max_inline_chars,
        args.allow_large_inline,
    )
    b64_data = base64.b64encode(image_data).decode('ascii')

    if len(image_data) > MAX_INLINE_SIZE:
        print(f"WARNING: Image is {len(image_data)} bytes after compression. "
              f"Very large base64 may cause issues.", file=sys.stderr)

    # Determine mime type (use JPEG if compressed, otherwise original)
    was_compressed = len(image_data) != original_size
    if was_compressed:
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
