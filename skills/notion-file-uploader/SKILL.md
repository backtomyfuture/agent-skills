---
name: notion-file-uploader
description: Upload local files (images, PDFs, videos, audio, and other files) directly to Notion pages using the Notion File Upload API. Use when you need to attach a local file to a Notion page as a content block. Supports png, jpg, gif, webp, svg, pdf, mp4, mov, mp3, wav, and more. Requires NOTION_API_KEY environment variable.
---

# Notion File Uploader

Upload local files to Notion pages via the Notion File Upload API (no third-party image hosting needed).

## Quick Usage

```bash
python scripts/upload_to_notion.py <file_path> <page_id>
```

## Prerequisites

- `NOTION_API_KEY` environment variable set
- `requests` library installed (`pip install requests`)
- File size ≤ 5GB (≤20MB single-part, >20MB auto multi-part)

## Workflow

1. **Detect block type** from file extension (or use `--block-type` to override):
   - `.png/.jpg/.gif/.webp/.svg` → `image` block
   - `.pdf` → `pdf` block
   - `.mp4/.mov/.webm` → `video` block
   - `.mp3/.wav/.ogg` → `audio` block
   - Other extensions → `file` block

2. **Run the upload script**:
   ```bash
   python scripts/upload_to_notion.py /path/to/file.pdf <page_id> --caption "Optional caption"
   ```

3. The script automatically selects single-part or multi-part mode:
   - **≤ 20MB**: single-part (create → send → attach)
   - **> 20MB**: multi-part (create → send parts at 10MB each → complete → attach)
   - Max file size: 5GB

## Examples

```bash
# Upload an image
python scripts/upload_to_notion.py photo.jpg abc123def456 --caption "Project screenshot"

# Upload a PDF
python scripts/upload_to_notion.py report.pdf abc123def456

# Upload a video
python scripts/upload_to_notion.py demo.mp4 abc123def456

# Force a specific block type
python scripts/upload_to_notion.py document.docx abc123def456 --block-type file

# JSON output for programmatic use
python scripts/upload_to_notion.py image.png abc123def456 --output json
```

## Programmatic Usage

The script can also be imported:

```python
from upload_to_notion import upload_file_to_notion

result = upload_file_to_notion("/path/to/file.png", "page-id-here", caption="My image")
if result["success"]:
    print(f"Uploaded as {result['block_type']} block, upload ID: {result['file_upload_id']}")
```

## Limitations

- Max file size: 5GB (paid workspace required for multi-part)
- Files must be attached within 1 hour of upload or the upload expires
- Notion-hosted file download URLs expire after 1 hour (re-fetch to refresh)
