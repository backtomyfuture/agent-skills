---
name: notion-to-md
description: >
  Convert a Notion page into Markdown with `notion-to-md` v4 from notionconvert.com.
  Use this skill whenever the user wants to export, sync, archive, mirror, back up, or transform
  a Notion page into `.md`, especially if they mention `notion-to-md`, `notionconvert`,
  "Notion 转 Markdown", "导出 Notion 为 md", preserving images/files, or building a reusable
  script/CLI around Notion content export. Also trigger when the user provides a Notion page URL
  and asks for Markdown output, local media downloads, or automation for Notion-to-Markdown flows.
---

# Notion to Markdown

Use the `notion-to-md` v4 workflow from notionconvert.com instead of hand-writing a Notion block renderer.

## What this skill is for

- One-off export of a Notion page to Markdown
- Saving Markdown to a file in a repo or local folder
- Downloading page media and rewriting links to local paths
- Adding a reusable conversion script or CLI to an existing project

## Guardrails

- Never hardcode the integration token. Prefer `NOTION_TOKEN`; `NOTION_API_KEY` is acceptable as a legacy alias.
- For the bundled helper on macOS, if neither environment variable is set, it can read the token from Keychain:
  - generic password service: `NOTION_TOKEN`
  - account: the current `$USER`
- If conversion fails with auth or access errors, first check that:
  - the Notion integration exists
  - the user is using the correct integration token
  - the target page was shared with that integration
- Match the repo's existing package manager, module system, and code style.
- If the project already has a Notion export pipeline, extend it instead of replacing it blindly.

## Default workflow

1. Inspect the repo to find the package manager and any existing Notion tooling.
2. Install or reuse:
   - `notion-to-md@alpha`
   - `@notionhq/client`
3. Use credentials safely:
   - project-specific scripts should read `process.env.NOTION_TOKEN` or `process.env.NOTION_API_KEY`
   - the bundled helper also falls back to macOS Keychain service `NOTION_TOKEN`
4. Accept either a page ID or a Notion page URL.
5. Extract the page ID if the input is a URL.
6. Choose the lightest implementation that satisfies the request:
   - direct conversion to a Markdown string
   - file export via `DefaultExporter`
   - file export plus media download via `downloadMediaTo(...)`
7. Run the conversion and verify the output file or stdout content.

## Preferred implementations

### 1. Basic conversion

Use this when the user wants the Markdown content directly:

```ts
import { Client } from '@notionhq/client';
import { NotionConverter } from 'notion-to-md';

const notion = new Client({
  auth: process.env.NOTION_TOKEN || process.env.NOTION_API_KEY,
});

const n2m = new NotionConverter(notion);
const result = await n2m.convert(pageId);
console.log(result.content);
```

The returned result includes:

- `content`
- `blocks`
- `properties`
- `metadata`

### 2. Save Markdown to a file

Use the built-in exporter instead of manually writing the file:

```ts
import { Client } from '@notionhq/client';
import { NotionConverter } from 'notion-to-md';
import { DefaultExporter } from 'notion-to-md/plugins/exporter';

const notion = new Client({ auth: process.env.NOTION_TOKEN || process.env.NOTION_API_KEY });
const exporter = new DefaultExporter({
  outputType: 'file',
  outputPath: './output/page.md',
});

await new NotionConverter(notion).withExporter(exporter).convert(pageId);
```

### 3. Save Markdown and download media

Use this when the user wants self-contained Markdown with stable local asset links:

```ts
import path from 'node:path';
import { Client } from '@notionhq/client';
import { NotionConverter } from 'notion-to-md';
import { DefaultExporter } from 'notion-to-md/plugins/exporter';

const notion = new Client({ auth: process.env.NOTION_TOKEN || process.env.NOTION_API_KEY });
const outputDir = './output';
const mediaDir = path.join(outputDir, 'media');

const exporter = new DefaultExporter({
  outputType: 'file',
  outputPath: path.join(outputDir, `${pageId}.md`),
});

await new NotionConverter(notion)
  .withExporter(exporter)
  .downloadMediaTo({
    outputDir: mediaDir,
    transformPath: (localPath) => `/media/${path.basename(localPath)}`,
  })
  .convert(pageId);
```

`transformPath` matters because Notion's original media URLs expire. Rewrite links to wherever the local files will actually be served from.

## Page ID handling

If the user gives a Notion URL, extract the page ID before conversion. Accept either:

- hyphenated UUID
- 32-character page ID embedded in the URL

Do not ask the user to manually reformat the ID if you can infer it.

## Reusable helper script

For one-off exports or small automation tasks, prefer the bundled helper:

- `scripts/convert_page.mjs`

It supports:

- page URL or page ID input
- stdout output
- file output
- optional media download directory
- optional media URL prefix rewriting
- credential lookup from `NOTION_TOKEN`, `NOTION_API_KEY`, then macOS Keychain service `NOTION_TOKEN`

Use it when the user wants a quick CLI instead of a project-specific implementation.

Examples:

```bash
node scripts/convert_page.mjs "<page-url-or-id>" --stdout
node scripts/convert_page.mjs "<page-url-or-id>" --output ./output/page.md
node scripts/convert_page.mjs "<page-url-or-id>" --output ./output/page.md --media-dir ./output/media --media-url-prefix ./media
```

If the user stores the token in macOS Keychain with:

```bash
security add-generic-password -a "$USER" -s "NOTION_TOKEN" -w "$NOTION_TOKEN_VALUE" -U
```

the helper can use it without requiring `export NOTION_TOKEN=...` in the current shell.

## Output expectations

- If the user asked for a file, report the exact output path.
- If media was downloaded, report both the Markdown file path and media directory.
- If you changed links via `transformPath`, mention the chosen public path prefix.
- If you only printed to stdout, avoid extra logging on stdout that would corrupt the Markdown stream.

## Error handling

- Missing credential: tell the user to set `NOTION_TOKEN`, set `NOTION_API_KEY`, or store the token in macOS Keychain as service `NOTION_TOKEN`.
- 401/403/404 from Notion: verify integration access and page sharing before changing code.
- Empty or malformed input: normalize the page ID or URL first.
- Media path issues: make sure `transformPath` matches how the files will be served or referenced.
