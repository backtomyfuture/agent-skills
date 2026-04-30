#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { Client } from '@notionhq/client';
import { NotionConverter } from 'notion-to-md';
import { DefaultExporter } from 'notion-to-md/plugins/exporter';
import { MDXRenderer } from 'notion-to-md/plugins/renderer';

function usage() {
  console.error(`Usage:
  node scripts/convert_page.mjs <page-id-or-url> [--output <file>] [--media-dir <dir>] [--media-url-prefix <prefix>] [--stdout]

Examples:
  node scripts/convert_page.mjs https://www.notion.so/workspace/My-Page-1234567890abcdef1234567890abcdef --stdout
  NOTION_TOKEN=secret node scripts/convert_page.mjs 1234567890abcdef1234567890abcdef --output ./output/page.md
  node scripts/convert_page.mjs <page> --output ./output/page.md --media-dir ./output/media --media-url-prefix /media

Credential lookup:
  1. NOTION_TOKEN
  2. NOTION_API_KEY
  3. macOS Keychain generic password with service "NOTION_TOKEN" and account "$USER"`);
}

function parseArgs(argv) {
  const args = {
    input: '',
    outputPath: '',
    mediaDir: '',
    mediaUrlPrefix: './media',
    stdout: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (!args.input && !arg.startsWith('--')) {
      args.input = arg;
      continue;
    }

    if (arg === '--output') {
      args.outputPath = argv[++i] ?? '';
      continue;
    }

    if (arg === '--media-dir') {
      args.mediaDir = argv[++i] ?? '';
      continue;
    }

    if (arg === '--media-url-prefix') {
      args.mediaUrlPrefix = argv[++i] ?? './media';
      continue;
    }

    if (arg === '--stdout') {
      args.stdout = true;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  if (!args.input) {
    usage();
    throw new Error('Missing page id or page url');
  }

  if (!args.outputPath && !args.stdout) {
    args.stdout = true;
  }

  return args;
}

function extractPageId(input) {
  const value = input.trim();
  const uuid = value.match(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/)?.[0];
  if (uuid) {
    return uuid.toLowerCase();
  }

  const compact = value.match(/[0-9a-fA-F]{32}/)?.[0];
  if (compact) {
    return compact.toLowerCase();
  }

  throw new Error(`Could not extract a Notion page id from: ${input}`);
}

function normalizePrefix(prefix) {
  const cleaned = prefix.replace(/\\/g, '/').replace(/\/+$/, '');
  return cleaned || '.';
}

function readTokenFromMacOSKeychain() {
  if (process.platform !== 'darwin') {
    return '';
  }

  const account = process.env.NOTION_KEYCHAIN_ACCOUNT || process.env.USER || process.env.LOGNAME;
  const service = process.env.NOTION_KEYCHAIN_SERVICE || 'NOTION_TOKEN';
  const args = ['find-generic-password', '-s', service, '-w'];

  if (account) {
    args.splice(1, 0, '-a', account);
  }

  try {
    return execFileSync('/usr/bin/security', args, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

function getNotionToken() {
  const token = process.env.NOTION_TOKEN || process.env.NOTION_API_KEY || readTokenFromMacOSKeychain();
  if (token) {
    return token;
  }

  throw new Error(
    'Notion credential is required. Set NOTION_TOKEN, set NOTION_API_KEY, or store a macOS Keychain generic password with service "NOTION_TOKEN".',
  );
}

function createMarkdownRenderer() {
  const renderer = new MDXRenderer();

  renderer.createBlockTransformer('heading_4', {
    transform: async ({ block, utils }) => {
      const headingBlock = block.heading_4;
      const isToggle = headingBlock.is_toggleable;
      const text = await utils.transformRichText(headingBlock.rich_text, {
        html: isToggle,
      });

      if (!isToggle) {
        return `#### ${text}\n\n`;
      }

      const childrenContent = block.children?.length
        ? await Promise.all(block.children.map((child) => utils.processBlock(child)))
        : [];

      return `<details>
  <summary>
  <h4>${text}</h4>
  </summary>

  ${childrenContent.join('\n')}

</details>
`;
    },
  });

  return renderer;
}

async function main() {
  const { input, outputPath, mediaDir, mediaUrlPrefix, stdout } = parseArgs(process.argv.slice(2));

  const notionToken = getNotionToken();
  const notion = new Client({ auth: notionToken });

  const pageId = extractPageId(input);
  let converter = new NotionConverter(notion).withRenderer(createMarkdownRenderer());

  if (outputPath) {
    const absoluteOutputPath = path.resolve(outputPath);
    await fs.mkdir(path.dirname(absoluteOutputPath), { recursive: true });
    converter = converter.withExporter(
      new DefaultExporter({
        outputType: 'file',
        outputPath: absoluteOutputPath,
      }),
    );
  }

  if (mediaDir) {
    const absoluteMediaDir = path.resolve(mediaDir);
    const prefix = normalizePrefix(mediaUrlPrefix);
    await fs.mkdir(absoluteMediaDir, { recursive: true });
    converter = converter.downloadMediaTo({
      outputDir: absoluteMediaDir,
      transformPath: (localPath) => path.posix.join(prefix, path.basename(localPath)),
    });
  }

  const result = await converter.convert(pageId);

  if (stdout) {
    process.stdout.write(result.content.endsWith('\n') ? result.content : `${result.content}\n`);
  }

  if (outputPath) {
    console.error(`Saved markdown to ${path.resolve(outputPath)}`);
  }

  if (mediaDir) {
    console.error(`Downloaded media to ${path.resolve(mediaDir)}`);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
