#!/usr/bin/env node
/**
 * 有道云笔记 — 全量导出（笔记 + 附件）
 *
 * 用法：
 *   node scripts/export-all.mjs <targetId> [outputDir]
 *
 *   targetId  — Chrome CDP target ID 前缀（从 cdp.mjs list 获取）
 *   outputDir — 本地输出目录（默认 ~/Downloads/youdao-export）
 */

import { execSync } from "child_process";
import { mkdirSync, readdirSync, renameSync, existsSync, statSync } from "fs";
import { join, resolve } from "path";
import { homedir } from "os";

// --- 配置 ---
const CDP_SCRIPT = resolve(import.meta.dirname, "..", "..", "chrome-cdp", "scripts", "cdp.mjs");
const TARGET = process.argv[2];
const OUTPUT_DIR = resolve(process.argv[3] || join(homedir(), "Downloads", "youdao-export"));
const TEMP_DL_DIR = join(OUTPUT_DIR, ".downloads");
const WAIT_CLICK = 2000;
const WAIT_MENU = 500;
const SKIP_FOLDERS = ["我的资源", "收藏笔记"];

if (!TARGET) {
  console.error("用法: node export-all.mjs <targetId> [outputDir]");
  process.exit(1);
}

// --- 工具函数 ---
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

function cdpEvalRaw(method, params) {
  try {
    return execSync(
      `node ${JSON.stringify(CDP_SCRIPT)} evalraw ${TARGET} ${method} ${JSON.stringify(JSON.stringify(params))}`,
      { encoding: "utf-8", timeout: 10000 }
    ).trim();
  } catch (e) {
    return "";
  }
}

function sleep(ms) {
  execSync(`sleep ${ms / 1000}`);
}

function snapshotDL() {
  if (!existsSync(TEMP_DL_DIR)) return new Set();
  return new Set(readdirSync(TEMP_DL_DIR));
}

function waitForNewFile(before, maxWait = 20000) {
  const start = Date.now();
  while (Date.now() - start < maxWait) {
    execSync("sleep 1");
    if (!existsSync(TEMP_DL_DIR)) continue;
    const after = readdirSync(TEMP_DL_DIR);
    for (const f of after) {
      if (!before.has(f) && !f.endsWith(".crdownload") && !f.endsWith(".tmp") && !f.startsWith(".")) {
        return f;
      }
    }
    if (after.some(f => f.endsWith(".crdownload"))) continue;
    if (Date.now() - start > 5000) break;
  }
  // 同时检查 ~/Downloads（导出为Word 有时不走 setDownloadBehavior）
  const dlDir = join(homedir(), "Downloads");
  if (existsSync(dlDir)) {
    const dlFiles = readdirSync(dlDir);
    for (const f of dlFiles) {
      if (f.endsWith(".docx") && !before.has(f)) {
        const stat = statSync(join(dlDir, f));
        if (Date.now() - stat.mtimeMs < 30000) return "~/" + f;
      }
    }
  }
  return null;
}

function normalizeForMatch(name) {
  return name.replace(/\.[^.]*$/, "").replace(/\s*\(\d+\)\s*$/, "").trim();
}

function fileExistsLocally(localDir, webTitle) {
  if (!existsSync(localDir)) return false;
  const files = readdirSync(localDir).filter(f => {
    try { return statSync(join(localDir, f)).isFile() && !f.startsWith("."); }
    catch { return false; }
  });
  const webNorm = normalizeForMatch(webTitle);
  const key = webNorm.substring(0, 18);
  return files.some(lf => {
    const lfNorm = normalizeForMatch(lf);
    return lfNorm === webNorm || lf === webTitle ||
      (key.length >= 5 && lfNorm.substring(0, 18) === key) ||
      (key.length >= 5 && lfNorm.includes(key));
  });
}

// --- 获取文件夹树 ---
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
console.log("=== 有道云笔记全量导出 ===");
console.log(`输出目录: ${OUTPUT_DIR}`);
console.log(`临时下载: ${TEMP_DL_DIR}\n`);

mkdirSync(OUTPUT_DIR, { recursive: true });
mkdirSync(TEMP_DL_DIR, { recursive: true });

// 设置 Chrome 下载路径
cdpEvalRaw("Page.setDownloadBehavior", { behavior: "allow", downloadPath: TEMP_DL_DIR });
console.log("✅ Chrome 下载路径已设置\n");

// 获取初始文件夹树
const initTree = getFolderTree();
const folders = buildPathTree(initTree);

console.log(`=== 文件夹树（${folders.length} 个）===`);
for (const f of folders) {
  const indent = "  ".repeat(f.pl / 12);
  console.log(`${indent}${f.path}`);
}

// 统计
let stats = { downloaded: 0, skipped: 0, failed: 0, total: 0 };

console.log(`\n=== 开始下载 ===\n`);

for (const folder of folders) {
  if (SKIP_FOLDERS.includes(folder.name)) {
    console.log(`⏭️  ${folder.path}（跳过）`);
    continue;
  }

  // 每次重新获取节点，通过名称查找当前 ID（避免虚拟列表跳位）
  const currentTree = getFolderTree();
  const node = currentTree.find(n => n.name === folder.name);
  if (!node) {
    console.log(`❓ ${folder.path} — 节点未找到，跳过`);
    continue;
  }

  cdpEval(`document.getElementById('${node.id}').click()`);
  sleep(WAIT_CLICK);

  // 获取文件列表（排除子文件夹）
  const json = cdpEval(`JSON.stringify([...document.querySelectorAll('.list-li.file-item')].map(function(e,i){var t=(e.querySelector('.list-li-title')||e).textContent.trim().split('\\n')[0].trim();var use=e.querySelector('use');var href=use?use.getAttribute('xlink:href'):'';return {index:i,title:t,type:href};}).filter(function(x){return x.type!=='#type_folder';}))`);

  let webFiles = [];
  try { webFiles = JSON.parse(json); } catch { continue; }

  if (webFiles.length === 0) {
    console.log(`📁 ${folder.path}（空文件夹）`);
    continue;
  }

  const localDir = join(OUTPUT_DIR, folder.path);
  mkdirSync(localDir, { recursive: true });

  console.log(`\n📁 ${folder.path}（${webFiles.length} 个文件）`);

  for (const wf of webFiles) {
    stats.total++;

    // 检查是否已存在
    if (fileExistsLocally(localDir, wf.title)) {
      console.log(`  ✅ 已存在: ${wf.title}`);
      stats.skipped++;
      continue;
    }

    const isNote = wf.type === "#type_note";
    const menuAction = isNote ? "导出为Word" : "下载";

    process.stdout.write(`  ⬇️  ${wf.title} [${menuAction}] ... `);

    // 重新获取文件列表中的正确索引（虚拟列表可能变化）
    // 通过标题匹配找到正确的元素
    const titleKey = wf.title.substring(0, 30).replace(/'/g, "\\'");
    const clickResult = cdpEval(`(function(){var items=[...document.querySelectorAll('.list-li.file-item')];for(var i=0;i<items.length;i++){var t=(items[i].querySelector('.list-li-title')||items[i]).textContent.trim().split('\\n')[0].trim();if(t.indexOf('${titleKey}')>=0){items[i].click();return 'ok:'+i;}}return 'not_found';})()`);

    if (!clickResult.startsWith("ok")) {
      console.log("❌ 未找到文件项");
      stats.failed++;
      continue;
    }
    sleep(WAIT_CLICK);

    // 显示工具栏菜单
    cdpEval("var ul=document.querySelector('.widget-menu');if(ul){ul.style.display='block';ul.style.visibility='visible';ul.style.opacity='1';}");
    sleep(WAIT_MENU);

    // 点击对应菜单项
    const before = snapshotDL();
    const dlResult = cdpEval(`(function(){var items=document.querySelectorAll('.widget-menu .toolbar-menu-item');for(var i=0;i<items.length;i++){var t=items[i].textContent.trim();if(t==='${menuAction}'){items[i].click();return 'ok';}}return 'not_found';})()`);

    if (dlResult !== "ok") {
      console.log(`❌ 未找到"${menuAction}"按钮`);
      stats.failed++;
      continue;
    }

    // 等待下载
    const newFile = waitForNewFile(before);
    if (newFile) {
      let src, fileName;
      if (newFile.startsWith("~/")) {
        // 文件下载到了 ~/Downloads
        fileName = newFile.substring(2);
        src = join(homedir(), "Downloads", fileName);
      } else {
        fileName = newFile;
        src = join(TEMP_DL_DIR, newFile);
      }
      const dest = join(localDir, fileName);
      try {
        renameSync(src, dest);
        console.log(`✅ ${fileName}`);
      } catch (e) {
        console.log(`✅ 已下载（移动失败: ${e.message}）`);
      }
      stats.downloaded++;
    } else {
      console.log("⚠️ 未检测到下载文件");
      stats.failed++;
    }
  }
}

// 清理：重命名 (1)(2) 后缀文件
console.log("\n=== 清理重复后缀文件 ===");
let renamed = 0;
function cleanDuplicateSuffixes(dir) {
  if (!existsSync(dir)) return;
  for (const f of readdirSync(dir)) {
    const fp = join(dir, f);
    if (statSync(fp).isDirectory()) {
      cleanDuplicateSuffixes(fp);
    } else if (/\s\(\d+\)\.\w+$/.test(f)) {
      const newName = f.replace(/\s\(\d+\)\./, ".");
      const newPath = join(dir, newName);
      if (!existsSync(newPath)) {
        renameSync(fp, newPath);
        renamed++;
      }
    }
  }
}
cleanDuplicateSuffixes(OUTPUT_DIR);
console.log(`✅ 重命名了 ${renamed} 个文件\n`);

// 统计
console.log("=== 导出完成 ===");
console.log(`📊 文件总数:  ${stats.total}`);
console.log(`✅ 新下载:    ${stats.downloaded}`);
console.log(`⏭️  已存在:    ${stats.skipped}`);
console.log(`❌ 失败:      ${stats.failed}`);
console.log(`🔧 重命名:    ${renamed}`);
console.log(`📁 输出目录:  ${OUTPUT_DIR}`);
