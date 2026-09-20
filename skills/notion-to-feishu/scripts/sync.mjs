#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import dns from 'node:dns';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { Client } from '@notionhq/client';
import { notionAstToFeishuXml, extractImagesFromAst, extractTogglesFromAst } from './notion_ast_to_feishu_xml.mjs';

// Resolve api.notion.com directly to avoid proxy fake-IP (198.18.*) ECONNRESET on macOS
const originalLookup = dns.lookup;
dns.lookup = (hostname, options, callback) => {
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  if (hostname === 'api.notion.com') {
    if (options && options.all) {
      return callback(null, [
        { address: '208.103.161.2', family: 4 },
        { address: '208.103.161.1', family: 4 }
      ]);
    }
    return callback(null, '208.103.161.2', 4);
  }
  return originalLookup(hostname, options, callback);
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function usage() {
  console.error(`Usage:
  node scripts/sync.mjs <notion-page-url-or-id> [--doc <feishu-doc-url-or-id>] [--title <doc-title>] [--work-dir <dir>] [--as <bot|user>] [--user]

Examples:
  node scripts/sync.mjs "https://app.notion.com/p/f148002/01-AI-WorkBuddy-ea61d340a1c44c1fa2414245b16403aa" --user
  node scripts/sync.mjs "ea61d340a1c44c1fa2414245b16403aa" --doc "EPWodmmw1oWMbgxsP9XcrfGMnCh" --as user
  node scripts/sync.mjs "ea61d340a1c44c1fa2414245b16403aa" --title "第 01 课｜AI 赋能认知与 WorkBuddy 全景"
`);
}

function extractFeishuDocId(input, asIdentity = 'user') {
  if (!input) return '';
  const trimmed = input.trim();
  const docxMatch = trimmed.match(/docx\/([a-zA-Z0-9]+)/);
  if (docxMatch) return docxMatch[1];
  
  const wikiMatch = trimmed.match(/wiki\/([a-zA-Z0-9]+)/);
  if (wikiMatch) {
    const wikiToken = wikiMatch[1];
    try {
      const res = runLarkCli([
        'api', 'GET', '/open-apis/wiki/v2/spaces/get_node',
        '--params', JSON.stringify({ token: wikiToken }),
        '--as', asIdentity
      ]);
      if (res.data?.node?.obj_token) {
        return res.data.node.obj_token;
      }
    } catch (e) {
      console.warn('Failed to resolve wiki node:', e.message);
    }
  }

  const tokenMatch = trimmed.match(/^[a-zA-Z0-9]{20,35}$/);
  if (tokenMatch) return tokenMatch[0];
  return trimmed;
}

function parseArgs(argv) {
  const args = {
    input: '',
    doc: '',
    title: '',
    workDir: path.resolve(process.cwd(), './.notion_to_feishu_tmp'),
    as: 'bot',
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!args.input && !arg.startsWith('--')) {
      args.input = arg;
      continue;
    }
    if (arg === '--doc' || arg === '--doc-id' || arg === '--target-doc') {
      args.doc = argv[++i] ?? '';
      continue;
    }
    if (arg === '--title') {
      args.title = argv[++i] ?? '';
      continue;
    }
    if (arg === '--work-dir') {
      args.workDir = path.resolve(argv[++i] ?? './.notion_to_feishu_tmp');
      continue;
    }
    if (arg === '--as') {
      args.as = argv[++i] ?? 'bot';
      continue;
    }
    if (arg === '--user') {
      args.as = 'user';
      continue;
    }
  }

  if (!args.input) {
    usage();
    process.exit(1);
  }

  return args;
}

function extractPageId(input) {
  const value = input.trim();
  const uuid = value.match(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/)?.[0];
  if (uuid) return uuid.toLowerCase();

  const compact = value.match(/[0-9a-fA-F]{32}/)?.[0];
  if (compact) return compact.toLowerCase();

  throw new Error(`Could not extract a Notion page ID from: ${input}`);
}

function readTokenFromMacOSKeychain() {
  if (process.platform !== 'darwin') return '';
  const account = process.env.NOTION_KEYCHAIN_ACCOUNT || process.env.USER || process.env.LOGNAME;
  const service = process.env.NOTION_KEYCHAIN_SERVICE || 'NOTION_TOKEN';
  const args = ['find-generic-password', '-s', service, '-w'];
  if (account) args.splice(1, 0, '-a', account);

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
  if (token) return token;
  throw new Error('Notion token not found in NOTION_TOKEN, NOTION_API_KEY or macOS Keychain.');
}

function runLarkCli(args, cwd = process.cwd()) {
  const stdout = execFileSync('lark-cli', args, { encoding: 'utf8', cwd });
  try {
    return JSON.parse(stdout);
  } catch {
    return stdout;
  }
}

function formatElements(richTextArray) {
  if (!richTextArray || !richTextArray.length) return [{ text_run: { content: '' } }];
  return richTextArray.map(t => {
    const ann = t.annotations || {};
    const style = {};
    if (ann.bold) style.bold = true;
    if (ann.italic) style.italic = true;
    if (ann.strikethrough) style.strikethrough = true;
    if (ann.underline) style.underline = true;
    if (ann.code) style.inline_code = true;
    if (t.href || t.text?.link?.url) style.link = { url: t.href || t.text.link.url };
    return {
      text_run: {
        content: t.plain_text || t.text?.content || '',
        text_element_style: Object.keys(style).length > 0 ? style : undefined
      }
    };
  });
}

function notionBlockToDocxBlock(b) {
  const type = b.type;
  const data = b[type];
  if (type === 'paragraph') {
    return {
      block_type: 2,
      text: { elements: formatElements(data.rich_text), style: { align: 1 } }
    };
  }
  if (type === 'bulleted_list_item') {
    return {
      block_type: 12,
      bullet: { elements: formatElements(data.rich_text), style: { align: 1 } }
    };
  }
  if (type === 'numbered_list_item') {
    return {
      block_type: 13,
      ordered: { elements: formatElements(data.rich_text), style: { align: 1 } }
    };
  }
  if (type === 'quote') {
    return {
      block_type: 15,
      quote: { elements: formatElements(data.rich_text), style: { align: 1 } }
    };
  }
  if (type === 'to_do') {
    return {
      block_type: 17,
      todo: { elements: formatElements(data.rich_text), style: { align: 1, done: !!data.checked } }
    };
  }
  if (type === 'code') {
    return {
      block_type: 14,
      code: { elements: [{ text_run: { content: data.rich_text?.map(t => t.plain_text).join('') || '' } }] }
    };
  }
  if (type === 'table') {
    const rows = b.children || [];
    const tableLines = [];
    for (const r of rows) {
      const cellTexts = r.table_row?.cells?.map(cell => cell.map(t => t.plain_text).join('').trim()) || [];
      tableLines.push(cellTexts.join(' ｜ '));
    }
    return {
      block_type: 15,
      quote: {
        elements: [{ text_run: { content: '📋 速查表格：\n' + tableLines.join('\n') } }],
        style: { align: 1 }
      }
    };
  }
  return {
    block_type: 2,
    text: { elements: [{ text_run: { content: data?.rich_text?.map(t => t.plain_text).join('') || '' } }] }
  };
}

async function fetchAllBlocksRecursive(notion, blockId) {
  let blocks = [];
  let cursor;
  do {
    const res = await notion.blocks.children.list({
      block_id: blockId,
      start_cursor: cursor,
      page_size: 100
    });
    for (const b of res.results) {
      blocks.push(b);
      if (b.has_children) {
        b.children = await fetchAllBlocksRecursive(notion, b.id);
      }
    }
    cursor = res.next_cursor;
  } while (cursor);
  return blocks;
}

async function main() {
  const { input, doc, title: customTitle, workDir, as: asIdentity } = parseArgs(process.argv.slice(2));
  const pageId = extractPageId(input);

  console.log(`🔍 [1/5] Connecting to Notion for page ${pageId}...`);
  const token = getNotionToken();
  const notion = new Client({ auth: token });

  // Retrieve Page Metadata
  const pageMeta = await notion.pages.retrieve({ page_id: pageId });
  let extractedTitle = customTitle;
  if (!extractedTitle) {
    for (const prop of Object.values(pageMeta.properties || {})) {
      if (prop.type === 'title' && prop.title?.length) {
        extractedTitle = prop.title.map(t => t.plain_text).join('').trim();
        break;
      }
    }
  }
  const finalTitle = extractedTitle || 'Notion 同步文档';
  console.log(`📄 Document Title: "${finalTitle}"`);

  // Fetch full AST
  console.log(`🔄 [2/5] Fetching Notion block hierarchy recursively...`);
  const blocks = await fetchAllBlocksRecursive(notion, pageId);
  console.log(`📦 Retrieved ${blocks.length} root blocks with complete child hierarchies.`);

  await fs.mkdir(workDir, { recursive: true });

  // Extract and download images locally to avoid AWS S3 Presigned URL timeouts in Feishu
  const imageBlocks = extractImagesFromAst(blocks);
  console.log(`🖼️ Found ${imageBlocks.length} images in Notion document.`);
  const downloadedImages = [];
  const imageMap = new Map();
  for (let imgIdx = 0; imgIdx < imageBlocks.length; imgIdx++) {
    const item = imageBlocks[imgIdx];
    try {
      console.log(`  ⬇️ Downloading image ${imgIdx + 1}/${imageBlocks.length}...`);
      const imgRes = await fetch(item.url);
      if (imgRes.ok) {
        const buf = Buffer.from(await imgRes.arrayBuffer());
        let ext = '.png';
        try {
          const parsed = new URL(item.url);
          const pExt = path.extname(parsed.pathname);
          if (pExt && ['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(pExt.toLowerCase())) {
            ext = pExt.toLowerCase();
          }
        } catch {}
        const fileName = `img_${imgIdx + 1}${ext}`;
        const filePath = path.join(workDir, fileName);
        await fs.writeFile(filePath, buf);
        const downloadedItem = {
          ...item,
          fileName,
          filePath,
        };
        downloadedImages.push(downloadedItem);
        imageMap.set(item.id, downloadedItem);
      }
    } catch (e) {
      console.warn(`  ⚠️ Failed to download image ${imgIdx + 1}:`, e.message);
    }
  }

  // Convert AST directly to Feishu Docx XML
  console.log(`🎨 [3/5] Converting Notion AST to high-fidelity Feishu Docx XML...`);
  const docXml = notionAstToFeishuXml(blocks, finalTitle, { imageMap });

  const xmlFileName = `${pageId}.xml`;
  const xmlPath = path.join(workDir, xmlFileName);
  await fs.writeFile(xmlPath, docXml, 'utf8');

  let docId = '';
  let docUrl = '';
  const targetDocId = extractFeishuDocId(doc, asIdentity);

  if (targetDocId) {
    console.log(`🚀 [4/5] Updating existing Feishu Docx document (${targetDocId}) via lark-cli (as: ${asIdentity})...`);
    const updateRes = runLarkCli([
      'docs', '+update',
      '--as', asIdentity,
      '--command', 'overwrite',
      '--doc-format', 'xml',
      '--content', `@./${xmlFileName}`,
      '--doc', targetDocId
    ], workDir);

    docId = targetDocId;
    docUrl = `https://feishu.cn/docx/${docId}`;
    console.log(`✅ Document updated: ${docUrl}`);
  } else {
    // Create Document in Feishu
    console.log(`🚀 [4/5] Creating Feishu Docx document via lark-cli (as: ${asIdentity})...`);
    const createRes = runLarkCli([
      'docs', '+create',
      '--as', asIdentity,
      '--doc-format', 'xml',
      '--content', `@./${xmlFileName}`
    ], workDir);

    if (!createRes.data || !createRes.data.document) {
      throw new Error(`Failed to create Feishu doc: ${JSON.stringify(createRes)}`);
    }

    docId = createRes.data.document.document_id;
    docUrl = createRes.data.document.url || `https://feishu.cn/docx/${docId}`;
    console.log(`✅ Document created: ${docUrl}`);

    // Grant full_access / transfer ownership to current CLI user if created as bot
    if (asIdentity === 'bot') {
      try {
        const authStatus = runLarkCli(['auth', 'status']);
        const userOpenId = authStatus?.userOpenId;
        if (userOpenId) {
          try {
            runLarkCli([
              'drive', 'permission.members', 'transfer_owner',
              '--as', 'bot',
              '--params', JSON.stringify({ token: docId, type: 'docx', stay_put: false, old_owner_perm: 'full_access' }),
              '--data', JSON.stringify({ member_type: 'openid', member_id: userOpenId }),
              '--yes'
            ]);
            console.log(`👤 Ownership transferred to user: ${authStatus.userName || userOpenId}`);
          } catch {
            runLarkCli([
              'drive', 'permission.members', 'create',
              '--as', 'bot',
              '--params', JSON.stringify({ token: docId, type: 'docx' }),
              '--data', JSON.stringify({ member_type: 'openid', member_id: userOpenId, perm: 'full_access' }),
              '--yes'
            ]);
            console.log(`👤 Granted full_access to user: ${authStatus.userName || userOpenId}`);
          }
        }
      } catch (e) {
        console.warn('  ⚠️ Failed to transfer/grant permission to user:', e.message);
      }
    }
  }

  // Patch Title
  try {
    runLarkCli([
      'drive', 'files', 'patch',
      '--params', JSON.stringify({ file_token: docId, type: 'docx' }),
      '--data', JSON.stringify({ new_title: finalTitle }),
      '--as', asIdentity
    ]);
  } catch (err) {
    console.warn('Title patch warning:', err.message);
  }

  // Attach native interactive Toggle blocks & children
  console.log(`⚙️ [5/5] Patching native interactive Toggle blocks (folded: true)...`);
  const toggles = extractTogglesFromAst(blocks);
  console.log(`📁 Found ${toggles.length} toggle blocks to process.`);

  let pageToken = '';
  let allBlocks = [];
  do {
    const listArgs = ['api', 'GET', `/open-apis/docx/v1/documents/${docId}/blocks`, '--as', asIdentity];
    if (pageToken) listArgs.push('--params', JSON.stringify({ page_token: pageToken }));
    const blockListRes = runLarkCli(listArgs);
    if (blockListRes.data?.items) {
      allBlocks.push(...blockListRes.data.items);
    }
    pageToken = blockListRes.data?.page_token || '';
  } while (pageToken);

  let foldedCount = 0;
  for (const toggle of toggles) {
    if (!toggle.children || toggle.children.length === 0) continue;

    // Match heading block in Lark docx
    const targetBlock = allBlocks.find(b => {
      const blockType = b.block_type;
      const isHeading = blockType >= 3 && blockType <= 11;
      if (!isHeading) return false;
      const headingData = b[Object.keys(b).find(k => k.startsWith('heading'))];
      const plain = headingData?.elements?.map(e => e.text_run?.content || '').join('').trim() || '';
      return plain === toggle.title || (plain && toggle.title && (plain.includes(toggle.title.slice(0, 10)) || toggle.title.includes(plain.slice(0, 10))));
    });

    if (targetBlock) {
      try {
        const docxChildren = toggle.children.map(c => notionBlockToDocxBlock(c));
        // Add children to the heading block
        runLarkCli([
          'api', 'POST', `/open-apis/docx/v1/documents/${docId}/blocks/${targetBlock.block_id}/children`,
          '--as', asIdentity,
          '--data', JSON.stringify({ children: docxChildren, index: 0 })
        ]);
        // Set folded: true
        runLarkCli([
          'api', 'PATCH', `/open-apis/docx/v1/documents/${docId}/blocks/${targetBlock.block_id}`,
          '--as', asIdentity,
          '--data', JSON.stringify({
            update_text_style: {
              style: { folded: true },
              fields: [3]
            }
          })
        ]);
        foldedCount++;
        console.log(`  ✅ Native Toggle attached & folded: "${toggle.title.slice(0, 30)}..."`);
      } catch (e) {
        console.warn(`  ⚠️ Failed to fold toggle "${toggle.title}":`, e.message);
      }
    }
  }

  // Also fold any other headings that have native children
  for (const block of allBlocks) {
    const isHeading = block.block_type >= 3 && block.block_type <= 11;
    if (isHeading && block.children && block.children.length > 0) {
      try {
        runLarkCli([
          'api', 'PATCH', `/open-apis/docx/v1/documents/${docId}/blocks/${block.block_id}`,
          '--as', asIdentity,
          '--data', JSON.stringify({
            update_text_style: {
              style: { folded: true },
              fields: [3]
            }
          })
        ]);
      } catch {}
    }
  }

  // Clean up temporary workDir
  try {
    await fs.rm(workDir, { recursive: true, force: true });
  } catch {}

  console.log(`\n🎉 Synchronized successfully!`);
  console.log(`📌 Document URL: ${docUrl}`);
  console.log(`📁 Toggle Sections Folded: ${foldedCount}`);
  console.log(`👤 User Permission: full_access (可管理)`);

  return {
    docId,
    docUrl,
    title: finalTitle,
    foldedCount
  };
}

main().catch((err) => {
  console.error('❌ Error during sync:', err.message);
  process.exit(1);
});
