/**
 * 有道云笔记 — Ego Lite 下载后验证
 *
 * `verifyExport({ page, outputDir })` is used by export-all.mjs and can also
 * be called from a separate Ego Lite round with the same TaskSpace.
 */

import { existsSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

const DEFAULT_OUTPUT_DIR = join(homedir(), "Downloads", "youdao-export");
const WAIT_CLICK = 1_500;
const SKIP_FOLDERS = ["我的资源", "收藏笔记"];

async function getFolderTree(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('[id^="filenode-"]')].map((element) => {
      const padding = parseInt(element.style.paddingLeft || "0", 10);
      const nameElement = element.querySelector(".file-name");
      const name =
        nameElement?.textContent?.trim() ||
        element.textContent?.trim().split("\n")[0].trim().slice(0, 80) ||
        "";
      return { id: element.id, name, pl: padding };
    }),
  );
}

function buildPathTree(flatNodes) {
  const stack = [];
  return flatNodes.map((folder) => {
    while (stack.length && stack.at(-1).pl >= folder.pl) stack.pop();
    const parent = stack.at(-1)?.path || "";
    const path = parent ? `${parent}/${folder.name}` : folder.name;
    stack.push({ pl: folder.pl, path });
    return { ...folder, path };
  });
}

async function clickFolder(page, folderName) {
  const clicked = await page.evaluate((name) => {
    const node = [...document.querySelectorAll('[id^="filenode-"]')].find(
      (element) =>
        (
          element.querySelector(".file-name") || element
        ).textContent
          .trim()
          .split("\n")[0]
          .trim() === name,
    );
    if (!node) return false;
    node.click();
    return true;
  }, folderName);
  if (clicked) await page.waitForTimeout(WAIT_CLICK);
  return clicked;
}

async function getFiles(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".list-li.file-item")]
      .map((element) => {
        const title = (
          element.querySelector(".list-li-title") || element
        ).textContent
          .trim()
          .split("\n")[0]
          .trim();
        const use = element.querySelector("use");
        return { title, type: use?.getAttribute("xlink:href") || "" };
      })
      .filter((file) => file.type !== "#type_folder"),
  );
}

function normalize(name) {
  return name
    .replace(/\.(docx|pdf|xlsx|pptx|doc|xls|ppt)$/i, "")
    .replace(/\s*\(\d+\)\s*$/, "")
    .trim();
}

function matches(webTitle, localName) {
  const webNorm = normalize(webTitle);
  const localNorm = normalize(localName);
  const key = webNorm.slice(0, 18);
  return (
    localNorm === webNorm ||
    localName === webTitle ||
    (key.length >= 5 && localNorm.slice(0, 18) === key) ||
    (key.length >= 5 && localNorm.includes(key))
  );
}

function localFiles(directory) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory).filter((file) => {
    try {
      return statSync(join(directory, file)).isFile() && !file.startsWith(".");
    } catch {
      return false;
    }
  });
}

function localDirectories(directory, base = directory) {
  if (!existsSync(directory)) return [];
  let result = [];
  for (const file of readdirSync(directory)) {
    if (file.startsWith(".")) continue;
    const path = join(directory, file);
    if (!statSync(path).isDirectory()) continue;
    result.push(path.slice(base.length + 1));
    result = result.concat(localDirectories(path, base));
  }
  return result;
}

export async function verifyExport({
  page,
  outputDir: requestedOutputDir = DEFAULT_OUTPUT_DIR,
} = {}) {
  if (!page) throw new Error("verifyExport requires an Ego Lite page");
  const outputDir = resolve(requestedOutputDir);
  const folders = buildPathTree(await getFolderTree(page));
  const missing = [];
  const extra = [];
  let totalWebFiles = 0;
  let totalLocalFiles = 0;

  for (const folder of folders) {
    if (SKIP_FOLDERS.includes(folder.name)) continue;
    if (!(await clickFolder(page, folder.name))) {
      missing.push({ folder: folder.path, reason: "folder_not_found" });
      continue;
    }

    const webFiles = await getFiles(page);
    const files = localFiles(join(outputDir, folder.path));
    totalWebFiles += webFiles.length;
    totalLocalFiles += files.length;

    for (const webFile of webFiles) {
      if (!files.some((localFile) => matches(webFile.title, localFile))) {
        missing.push({ folder: folder.path, ...webFile });
      }
    }
    for (const localFile of files) {
      if (!webFiles.some((webFile) => matches(webFile.title, localFile))) {
        extra.push({ folder: folder.path, file: localFile });
      }
    }
  }

  const webFolderPaths = new Set(folders.map((folder) => folder.path));
  const extraDirs = localDirectories(outputDir).filter(
    (directory) => !webFolderPaths.has(directory),
  );
  return {
    success: missing.length === 0 && extra.length === 0 && extraDirs.length === 0,
    totalWebFiles,
    totalLocalFiles,
    webFolderCount: folders.length,
    localFolderCount: localDirectories(outputDir).length,
    missing,
    extra,
    extraDirs,
  };
}
