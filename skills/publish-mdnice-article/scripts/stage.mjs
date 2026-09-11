const EDITOR_URL = "https://editor.mdnice.com/";
const EDITOR_SELECTOR = "#nice-md-editor";
const LOGIN_WAIT_MS = 15_000;
const IMAGE_WAIT_MS = 500;

function required(value, name) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} is required`);
  }
  return String(value);
}

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null);
}

function visible(element) {
  return Boolean(element && element.offsetParent !== null);
}

async function loadScript(scriptPath, name) {
  const path = required(scriptPath, name);
  const { readFile } = await import("node:fs/promises");
  return readFile(path, "utf8");
}

async function pageForTask(task) {
  const existing = (await task.tabs()).find((tab) =>
    tab.url?.includes("editor.mdnice.com"),
  );
  if (existing?.label) return task.page(existing.label);
  if (existing?.page) return task.adopt(existing.page);
  return task.page("p1");
}

async function editorReady(page) {
  return page
    .waitForFunction(
      (selector) => {
        const editor = document.querySelector(selector);
        return Boolean(editor && (editor.offsetParent !== null || editor.getClientRects().length));
      },
      EDITOR_SELECTOR,
      { timeout: LOGIN_WAIT_MS },
    )
    .then(() => true)
    .catch(() => false);
}

async function clickNewArticle(page) {
  await page.click(EDITOR_SELECTOR, { label: "focus Markdown editor" });
  await page.waitForTimeout(300);

  const clicked = await page.evaluate(() => {
    const candidates = [
      ...document.querySelectorAll("button, a, [role='button'], [role='menuitem']"),
    ].filter((element) => {
      const text = element.textContent?.trim() || "";
      return element.offsetParent !== null && text.includes("新建文章");
    });
    candidates[0]?.click();
    return candidates.length > 0;
  });
  if (!clicked) {
    await page.click('text="新建文章"', { label: "open new article dialog" });
  }
}

async function fillTitle(page, { title, titleJsPath }) {
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll(".ant-modal-content")].some(
        (modal) =>
          modal.offsetParent !== null &&
          Boolean(modal.querySelector(".ant-modal-body input")),
      ),
    undefined,
    { timeout: 10_000 },
  );

  if (titleJsPath) {
    const result = await page.evaluate(await loadScript(titleJsPath, "titleJsPath"));
    if (!result?.ok) {
      throw new Error(`Title script failed: ${JSON.stringify(result)}`);
    }
    return result;
  }

  const result = await page.evaluate((value) => {
    const isVisible = (element) =>
      Boolean(element && element.offsetParent !== null);
    const modal = [...document.querySelectorAll(".ant-modal-content")].find(
      isVisible,
    );
    const inputs = [...(modal?.querySelectorAll(".ant-modal-body input") || [])];
    const input =
      inputs.find((element) => element.placeholder === "请输入标题") ||
      inputs.find((element) =>
        (element.closest(".ant-row, .ant-form-item, div")?.textContent || "").includes(
          "文章标题",
        ),
      ) ||
      inputs[0];
    if (!input) return { ok: false, error: "title input not found" };

    const descriptor = Object.getOwnPropertyDescriptor(
      Object.getPrototypeOf(input),
      "value",
    );
    input.focus();
    if (descriptor?.set) descriptor.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));

    const button =
      modal?.querySelector(".ant-modal-footer .ant-btn-primary") ||
      [...document.querySelectorAll(".ant-modal-footer .ant-btn-primary, button.ant-btn-primary")].find(
        isVisible,
      );
    if (!button) return { ok: false, error: "confirm button not found" };
    button.click();
    return { ok: true, title: value };
  }, title);
  if (!result?.ok) {
    throw new Error(`Title fill failed: ${JSON.stringify(result)}`);
  }
  return result;
}

async function deleteMarker(page, marker) {
  return page.evaluate((value) => {
    const editor = document.querySelector("#nice-md-editor");
    const cm = editor?.querySelector(".CodeMirror")?.CodeMirror ||
      document.querySelector(".CodeMirror")?.CodeMirror;
    if (cm) {
      const source = cm.getValue();
      const start = source.indexOf(value);
      if (start < 0) return { ok: false, error: "marker not found" };
      const from = cm.posFromIndex(start);
      const to = cm.posFromIndex(start + value.length);
      cm.replaceRange("", from, to);
      cm.setCursor(from);
      cm.focus();
      if (typeof cm.save === "function") cm.save();
      return { ok: true, method: "codemirror", position: start };
    }

    if (!editor) return { ok: false, error: "editor not found" };
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const start = node.textContent.indexOf(value);
      if (start < 0) continue;
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, start + value.length);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      range.deleteContents();
      return { ok: true, method: "dom" };
    }
    return { ok: false, error: "marker not found" };
  }, marker);
}

async function verifyEditor(page) {
  return page.evaluate(() => {
    const editor = document.querySelector("#nice-md-editor");
    const cm = editor?.querySelector(".CodeMirror")?.CodeMirror ||
      document.querySelector(".CodeMirror")?.CodeMirror;
    const value = cm?.getValue?.() ||
      (editor && "value" in editor ? editor.value : editor?.textContent) ||
      "";
    return {
      length: value.length,
      markerCount: (value.match(/\[\[IMG_\d+\]\]/g) || []).length,
      method: cm ? "codemirror" : "editor",
    };
  });
}

export async function stage(options = {}) {
  const title = required(options.title, "title");
  const contentJsPath = firstDefined(
    options.contentJsPath,
    options.contentScriptPath,
    options.contentFile,
  );
  required(contentJsPath, "contentJsPath");

  const task = options.taskSpaceId
    ? await takeOverTaskSpace(options.taskSpaceId)
    : await taskSpace("Stage Markdown Nice article");
  const page = await pageForTask(task);

  const currentUrl = await page.url();
  if (!currentUrl?.includes("editor.mdnice.com")) {
    await page.goto(EDITOR_URL);
  }

  if (!(await editorReady(page))) {
    const report = {
      status: "login_required",
      taskSpaceId: task.spaceId,
      url: await page.url(),
      submitted: false,
    };
    console.log(JSON.stringify(report));
    await task.handOff();
    return report;
  }

  await clickNewArticle(page);
  await fillTitle(page, {
    title,
    titleJsPath: firstDefined(options.titleJsPath, options.titleScriptPath),
  });
  await page.waitForTimeout(500);

  const contentResult = await page.evaluate(
    await loadScript(contentJsPath, "contentJsPath"),
  );
  if (!contentResult?.success) {
    throw new Error(`Content script failed: ${JSON.stringify(contentResult)}`);
  }

  const images = options.images || [];
  for (const image of images) {
    const marker = image.marker || `[[IMG_${image.index}]]`;
    const imageJsPath = firstDefined(
      image.jsPath,
      image.jsFile,
      image.js_file,
      image.imageJsPath,
      image.pasteJsPath,
    );
    required(imageJsPath, `image JS path for ${marker}`);

    const deletion = await deleteMarker(page, marker);
    if (!deletion?.ok) {
      throw new Error(`Could not delete ${marker}: ${JSON.stringify(deletion)}`);
    }
    await page.waitForTimeout(IMAGE_WAIT_MS);

    const imageResult = await page.evaluate(await loadScript(imageJsPath, imageJsPath));
    if (!imageResult?.ok) {
      throw new Error(`Image script failed for ${marker}: ${JSON.stringify(imageResult)}`);
    }
    await page.waitForTimeout(1_000);
  }

  await page.waitForTimeout(2_000);
  const verification = await verifyEditor(page);
  if (verification.length <= 0 || verification.markerCount !== 0) {
    throw new Error(`Editor verification failed: ${JSON.stringify(verification)}`);
  }

  const { mkdir } = await import("node:fs/promises");
  await mkdir("/tmp/mdnice-article", { recursive: true });
  const screenshotPath = `/tmp/mdnice-article/filled-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });

  const report = {
    status: "filled_preview",
    taskSpaceId: task.spaceId,
    screenshotPath,
    verification,
    submitted: false,
  };
  console.log(JSON.stringify(report));
  await task.handOff();
  return report;
}
