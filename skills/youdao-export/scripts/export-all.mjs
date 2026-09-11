/**
 * 有道云笔记 — Ego Lite 全量导出（笔记 + 附件）
 *
 * Run this module from `ego-browser nodejs`. It keeps the same TaskSpace
 * across manual login and export/verification rounds.
 */

import {
  existsSync,
  readdirSync,
  renameSync,
  statSync,
} from "node:fs";
import { mkdir } from "node:fs/promises";
import { basename, join, resolve } from "node:path";
import { homedir } from "node:os";
import { verifyExport } from "./verify.mjs";

const NOTE_URL = "https://note.youdao.com/web";
const DEFAULT_OUTPUT_DIR = join(homedir(), "Downloads", "youdao-export");
const WAIT_CLICK = 1_500;
const WAIT_MENU = 500;
const SKIP_FOLDERS = ["我的资源", "收藏笔记"];

function outputPath(value) {
  return resolve(value || DEFAULT_OUTPUT_DIR);
}

function currentPage(task) {
  return task.page("p1");
}

async function waitForNotebook(page, timeout = 15_000) {
  try {
    await page.waitForFunction(
      () =>
        location.hostname.includes("youdao.com") &&
        document.querySelectorAll('[id^="filenode-"]').length > 0,
      undefined,
      { timeout },
    );
    return true;
  } catch {
    return false;
  }
}

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
  const result = await page.evaluate((name) => {
    const node = [...document.querySelectorAll('[id^="filenode-"]')].find(
      (element) => {
        const visibleName =
          element.querySelector(".file-name")?.textContent?.trim() ||
          element.textContent?.trim().split("\n")[0].trim();
        return visibleName === name;
      },
    );
    if (!node) return { ok: false };
    node.click();
    return { ok: true, id: node.id };
  }, folderName);
  if (!result.ok) return false;
  await page.waitForTimeout(WAIT_CLICK);
  return true;
}

async function getFiles(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".list-li.file-item")]
      .map((element, index) => {
        const title = (
          element.querySelector(".list-li-title") || element
        ).textContent
          .trim()
          .split("\n")[0]
          .trim();
        const use = element.querySelector("use");
        return {
          index,
          title,
          type: use?.getAttribute("xlink:href") || "",
        };
      })
      .filter((file) => file.type !== "#type_folder"),
  );
}

function normalizeForMatch(name) {
  return name
    .replace(/\.[^.]*$/, "")
    .replace(/\s*\(\d+\)\s*$/, "")
    .trim();
}

function fileExistsLocally(localDir, webTitle) {
  if (!existsSync(localDir)) return false;
  const files = readdirSync(localDir).filter((file) => {
    try {
      return statSync(join(localDir, file)).isFile() && !file.startsWith(".");
    } catch {
      return false;
    }
  });
  const webNorm = normalizeForMatch(webTitle);
  const key = webNorm.slice(0, 18);
  return files.some((file) => {
    const localNorm = normalizeForMatch(file);
    return (
      localNorm === webNorm ||
      file === webTitle ||
      (key.length >= 5 && localNorm.slice(0, 18) === key) ||
      (key.length >= 5 && localNorm.includes(key))
    );
  });
}

function uniqueDestination(directory, filename) {
  const safeName = basename(filename) || "download";
  const extension = safeName.includes(".")
    ? safeName.slice(safeName.lastIndexOf("."))
    : "";
  const stem = extension ? safeName.slice(0, -extension.length) : safeName;
  let candidate = join(directory, safeName);
  let suffix = 1;
  while (existsSync(candidate)) {
    candidate = join(directory, `${stem} (${suffix})${extension}`);
    suffix += 1;
  }
  return candidate;
}

async function downloadFile(page, title, action, destinationDirectory) {
  const itemFound = await page.evaluate((fileTitle) => {
    const item = [...document.querySelectorAll(".list-li.file-item")].find(
      (element) =>
        (
          element.querySelector(".list-li-title") || element
        ).textContent
          .trim()
          .split("\n")[0]
          .trim()
          .startsWith(fileTitle.slice(0, 30)),
    );
    if (!item) return false;
    item.click();
    return true;
  }, title);
  if (!itemFound) return { ok: false, reason: "file_not_found" };

  await page.waitForTimeout(WAIT_CLICK);
  await page.evaluate(() => {
    const menu = document.querySelector(".widget-menu");
    if (menu) {
      menu.style.display = "block";
      menu.style.visibility = "visible";
      menu.style.opacity = "1";
    }
  });
  await page.waitForTimeout(WAIT_MENU);

  const menuActionAvailable = await page.evaluate(
    (menuAction) =>
      [...document.querySelectorAll(".widget-menu .toolbar-menu-item")].some(
        (element) => element.textContent?.trim() === menuAction,
      ),
    action,
  );
  if (!menuActionAvailable) {
    return { ok: false, reason: `menu_not_found:${action}` };
  }

  const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
  const menuClicked = await page.evaluate((menuAction) => {
    const item = [...document.querySelectorAll(".widget-menu .toolbar-menu-item")].find(
      (element) => element.textContent?.trim() === menuAction,
    );
    if (!item) return false;
    item.click();
    return true;
  }, action);
  if (!menuClicked) return { ok: false, reason: `menu_not_found:${action}` };

  const download = await downloadPromise;
  const destination = uniqueDestination(
    destinationDirectory,
    download.suggestedFilename(),
  );
  await download.saveAs(destination);
  return {
    ok: true,
    filename: basename(destination),
    path: destination,
  };
}

function cleanDuplicateSuffixes(directory) {
  if (!existsSync(directory)) return 0;
  let renamed = 0;
  for (const file of readdirSync(directory)) {
    const filePath = join(directory, file);
    if (statSync(filePath).isDirectory()) {
      renamed += cleanDuplicateSuffixes(filePath);
    } else if (/\s\(\d+\)\.\w+$/.test(file)) {
      const nextPath = join(directory, file.replace(/\s\(\d+\)\./, "."));
      if (!existsSync(nextPath)) {
        renameSync(filePath, nextPath);
        renamed += 1;
      }
    }
  }
  return renamed;
}

async function findOrCreateTask(taskSpaceId) {
  return taskSpaceId
    ? takeOverTaskSpace(Number(taskSpaceId))
    : taskSpace("Youdao Cloud Notes export");
}

export async function exportAll({
  taskSpaceId,
  outputDir: requestedOutputDir,
} = {}) {
  const outputDir = outputPath(requestedOutputDir);
  const task = await findOrCreateTask(taskSpaceId);
  const page = currentPage(task);

  if (!(await waitForNotebook(page, 3_000))) {
    await page.goto(NOTE_URL);
  }
  if (!(await waitForNotebook(page))) {
    console.log(
      JSON.stringify({
        status: "login_required",
        taskSpaceId: task.spaceId,
        url: await page.url(),
      }),
    );
    await task.handOff();
    return;
  }

  await mkdir(outputDir, { recursive: true });
  const folders = buildPathTree(await getFolderTree(page));
  const stats = {
    total: 0,
    downloaded: 0,
    skipped: 0,
    failed: 0,
  };

  for (const folder of folders) {
    if (SKIP_FOLDERS.includes(folder.name)) continue;
    const currentTree = await getFolderTree(page);
    if (!currentTree.some((node) => node.name === folder.name)) {
      stats.failed += 1;
      continue;
    }
    if (!(await clickFolder(page, folder.name))) {
      stats.failed += 1;
      continue;
    }

    const files = await getFiles(page);
    const localDir = join(outputDir, folder.path);
    await mkdir(localDir, { recursive: true });

    for (const file of files) {
      stats.total += 1;
      if (fileExistsLocally(localDir, file.title)) {
        stats.skipped += 1;
        continue;
      }

      const action = file.type === "#type_note" ? "导出为Word" : "下载";
      try {
        const result = await downloadFile(page, file.title, action, localDir);
        if (result.ok) stats.downloaded += 1;
        else stats.failed += 1;
      } catch {
        stats.failed += 1;
      }
    }
  }

  const renamed = cleanDuplicateSuffixes(outputDir);
  const verification = await verifyExport({ page, outputDir });
  await mkdir("/tmp/youdao-export", { recursive: true });
  const screenshotPath = `/tmp/youdao-export/verified-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });
  const result = {
    status: verification.success ? "verified" : "verification_failed",
    taskSpaceId: task.spaceId,
    outputDir,
    stats: { ...stats, renamed },
    verification,
    screenshotPath,
  };
  console.log(JSON.stringify(result, null, 2));
  if (verification.success) {
    await task.finish({ keep: [] });
  } else {
    await task.handOff();
  }
  return result;
}
