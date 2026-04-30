#!/usr/bin/env node
/**
 * 有道云笔记 — 下载后验证
 *
 * 逐文件夹对比网页与本地文件，确保无遗漏。
 *
 * 用法：
 *   node scripts/verify.mjs <targetId> [outputDir]
 */

import { execSync } from "child_process";
import { readdirSync, existsSync, statSync } from "fs";
import { join, resolve } from "path";
import { homedir } from "os";

const CDP_SCRIPT = resolve(import.meta.dirname, "..", "..", "chrome-cdp", "scripts", "cdp.mjs");
const TARGET = process.argv[2];
const OUTPUT_DIR = resolve(process.argv[3] || join(homedir(), "Downloads", "youdao-export"));
const SKIP_FOLDERS = ["我的资源", "收藏笔记"];

if (!TARGET) {
  console.error("用法: node verify.mjs <targetId> [outputDir]");
  process.exit(1);
}

function cdpEval(expr) {
  try {
    return execSync(
      `node ${JSON.stringify(CDP_SCRIPT)} eval ${TARGET} ${JSON.stringify(expr)}`,
      { encoding: "utf-8", timeout: 30000 }
    ).trim();
  } catch (e) {
    return "";
  }
}

function sleep(ms) {
  execSync(`sleep ${ms / 1000}`);
}

function normalize(name) {
  return name.replace(/\.(docx|pdf|xlsx|pptx|doc|xls|ppt)$/i, "").replace(/\s*\(\d+\)\s*$/, "").trim();
}

// 获取文件夹树
function getFolderTree() {
  const raw = cdpEval(`JSON.stringify([...document.querySelectorAll('[id^="filenode-"]')].map(function(e){var pl=parseInt(e.style.paddingLeft)||0;var nameEl=e.querySelector('.file-name');var name=nameEl?nameEl.textContent.trim():e.textContent.trim().split('\\n')[0].trim().substring(0,80);return {id:e.id,name:name,pl:pl};}))`);
  return JSON.parse(raw);
}

function buildPathTree(flatNodes) {
  const stack = [];
  const result = [];
  for (const f of flatNodes) {
    while (stack.length > 0 && stack[stack.length - 1].pl >= f.pl) stack.pop();
    const parent = stack.length > 0 ? stack[stack.length - 1].path : "";
    const fullPath = parent ? parent + "/" + f.name : f.name;
    result.push({ id: f.id, name: f.name, path: fullPath, pl: f.pl });
    stack.push({ pl: f.pl, path: fullPath });
  }
  return result;
}

// --- 主流程 ---
const initTree = getFolderTree();
const folders = buildPathTree(initTree);

console.log("=== 网页文件夹树 ===");
for (const f of folders) {
  const indent = "  ".repeat(f.pl / 12);
  console.log(`${indent}${f.path}`);
}

console.log(`\n=== 开始验证（${folders.length} 个文件夹）===\n`);

let totalWebFiles = 0;
let totalLocalFiles = 0;
let allMissing = [];
let allExtra = [];

for (const folder of folders) {
  if (SKIP_FOLDERS.includes(folder.name)) {
    console.log(`⏭️  ${folder.path}（跳过）`);
    continue;
  }

  // 每次重新获取节点（避免虚拟列表跳位）
  const currentTree = getFolderTree();
  const node = currentTree.find(n => n.name === folder.name);
  if (!node) {
    console.log(`❓ ${folder.path} — 节点未找到`);
    continue;
  }

  // 点击前记录当前文件列表的标识，用于检测是否刷新
  const prevJson = cdpEval(`JSON.stringify([...document.querySelectorAll('.list-li.file-item')].map(function(e){return (e.querySelector('.list-li-title')||e).textContent.trim().split('\\n')[0].trim();}))`);

  cdpEval(`document.getElementById('${node.id}').click()`);
  sleep(2000);

  // 重试机制：等待文件列表刷新（最多重试3次）
  let json = "";
  for (let retry = 0; retry < 3; retry++) {
    json = cdpEval(`JSON.stringify([...document.querySelectorAll('.list-li.file-item')].map(function(e){var t=(e.querySelector('.list-li-title')||e).textContent.trim().split('\\n')[0].trim();var use=e.querySelector('use');var href=use?use.getAttribute('xlink:href'):'';return {title:t,type:href};}).filter(function(x){return x.type!=='#type_folder';}))`);
    // 如果文件列表变化了或首次访问，认为已刷新
    const curTitles = JSON.stringify(JSON.parse(json || "[]").map(f => f.title));
    if (curTitles !== prevJson || retry === 0) break;
    sleep(1500);
  }

  let webFiles = [];
  try { webFiles = JSON.parse(json); } catch { continue; }

  const localDir = join(OUTPUT_DIR, folder.path);
  let localFiles = [];
  if (existsSync(localDir)) {
    localFiles = readdirSync(localDir).filter(f => {
      try { return statSync(join(localDir, f)).isFile() && !f.startsWith("."); }
      catch { return false; }
    });
  }

  totalWebFiles += webFiles.length;
  totalLocalFiles += localFiles.length;

  // 网页有但本地没有
  let missing = [];
  for (const wf of webFiles) {
    const webNorm = normalize(wf.title);
    const key = webNorm.substring(0, 18);
    const found = localFiles.some(lf => {
      const lfNorm = normalize(lf);
      return lfNorm === webNorm || lf === wf.title ||
        (key.length >= 5 && lfNorm.substring(0, 18) === key) ||
        (key.length >= 5 && lfNorm.includes(key));
    });
    if (!found) missing.push(wf);
  }

  // 本地有但网页没有
  let extra = [];
  for (const lf of localFiles) {
    const lfNorm = normalize(lf);
    const key = lfNorm.substring(0, 18);
    const found = webFiles.some(wf => {
      const wfNorm = normalize(wf.title);
      return wfNorm === lfNorm || wf.title === lf ||
        (key.length >= 5 && wfNorm.substring(0, 18) === key) ||
        (key.length >= 5 && wfNorm.includes(key));
    });
    if (!found) extra.push(lf);
  }

  const status = missing.length === 0 ? "✅" : "⚠️";
  const extraMark = extra.length > 0 ? ` (+${extra.length}本地多余)` : "";
  console.log(`${status} ${folder.path}: 网页${webFiles.length}/本地${localFiles.length}${missing.length > 0 ? ` 缺${missing.length}` : ""}${extraMark}`);

  if (missing.length > 0) {
    for (const m of missing) console.log(`     ❌ 缺: ${m.title} (${m.type})`);
    allMissing.push(...missing.map(m => ({ folder: folder.path, ...m })));
  }
  if (extra.length > 0) {
    for (const e of extra) console.log(`     ➕ 多: ${e}`);
    allExtra.push(...extra.map(e => ({ folder: folder.path, file: e })));
  }
}

// 检查本地多出的文件夹
const webFolderPaths = new Set(folders.map(f => f.path));
function walkDirs(dir, base) {
  let dirs = [];
  try {
    for (const f of readdirSync(dir)) {
      const fp = join(dir, f);
      if (statSync(fp).isDirectory() && !f.startsWith(".")) {
        const rel = fp.substring(base.length + 1);
        dirs.push(rel);
        dirs = dirs.concat(walkDirs(fp, base));
      }
    }
  } catch (e) {}
  return dirs;
}
const localDirs = walkDirs(OUTPUT_DIR, OUTPUT_DIR);
const extraDirs = localDirs.filter(d => !webFolderPaths.has(d));

// --- 汇总 ---
console.log(`\n${"=".repeat(40)}`);
console.log(`  验证结果汇总`);
console.log(`${"=".repeat(40)}`);
console.log(`  网页文件总数:   ${totalWebFiles}`);
console.log(`  本地文件总数:   ${totalLocalFiles}`);
console.log(`  网页文件夹数:   ${folders.length}`);
console.log(`  本地文件夹数:   ${localDirs.length}`);
console.log(`  缺失文件:       ${allMissing.length}`);
console.log(`  多余文件:       ${allExtra.length}`);
console.log(`  多余文件夹:     ${extraDirs.length}`);

if (allMissing.length === 0 && extraDirs.length === 0 && allExtra.length === 0) {
  console.log(`\n✅✅✅ 完全一致！所有文件和文件夹均匹配。`);
} else {
  if (allMissing.length > 0) {
    console.log(`\n⚠️  缺失 ${allMissing.length} 个文件：`);
    for (const m of allMissing) console.log(`  [${m.folder}] ${m.title} (${m.type})`);
  }
  if (extraDirs.length > 0) {
    console.log(`\n📁 本地多出的文件夹（${extraDirs.length}个）：`);
    for (const d of extraDirs) console.log(`  + ${d}`);
  }
  if (allExtra.length > 0) {
    console.log(`\n📄 本地多出的文件（${allExtra.length}个）：`);
    for (const e of allExtra) console.log(`  + [${e.folder}] ${e.file}`);
  }
}
