import { mkdir, readFile } from "node:fs/promises";

const ARTICLE_URL =
  "https://wx.zsxq.com/article?groupId=88882188185282";
const TITLE_SELECTOR = 'input[placeholder="请在这里输入标题"]';
const EDITOR_SELECTOR = ".ProseMirror";

function required(value, name) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} is required`);
  }
  return String(value);
}

async function articlePage(task) {
  const tab = (await task.tabs()).find((item) =>
    /wx\.zsxq\.com\/(?:article|login)/.test(item.url || ""),
  );
  if (tab) return tab.label ? task.page(tab.label) : task.adopt(tab.page);
  return task.page("p1");
}

async function pageState(page) {
  return page.evaluate((titleSelector) => ({
    url: location.href,
    login:
      /\/login(?:[/?#]|$)/.test(location.pathname) ||
      Boolean(document.querySelector('[href*="/login"]')) &&
        !document.querySelector(".ProseMirror"),
    title: Boolean(document.querySelector(titleSelector)),
    proseMirror: Boolean(document.querySelector(".ProseMirror")),
    quill: Boolean(document.querySelector(".ql-editor")),
  }), TITLE_SELECTOR);
}

async function waitForEditorOrLogin(page) {
  await page
    .waitForFunction(
      (titleSelector) =>
        /\/login(?:[/?#]|$)/.test(location.pathname) ||
        Boolean(document.querySelector(titleSelector)) ||
        Boolean(document.querySelector(".ProseMirror")) ||
        Boolean(document.querySelector(".ql-editor")),
      TITLE_SELECTOR,
      { timeout: 20_000 },
    )
    .catch(() => {});
}

async function deleteMarker(page, marker) {
  return page.evaluate((value) => {
    const editor = document.querySelector(".ProseMirror");
    const view = editor?.pmViewDesc?.view;
    if (view) {
      let position = -1;
      view.state.doc.descendants((node, pos) => {
        if (position !== -1) return false;
        if (node.isText && node.text?.includes(value)) {
          position = pos + node.text.indexOf(value);
          return false;
        }
        return undefined;
      });
      if (position !== -1) {
        view.dispatch(view.state.tr.delete(position, position + value.length));
        view.focus();
        return { ok: true, method: "pm", position };
      }
    }

    if (!editor) return { ok: false, error: "ProseMirror editor not found" };
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent || "";
      const index = text.indexOf(value);
      if (index === -1) continue;
      const range = document.createRange();
      range.setStart(walker.currentNode, index);
      range.setEnd(walker.currentNode, index + value.length);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      range.deleteContents();
      return { ok: true, method: "dom" };
    }
    return { ok: false, error: "marker not found" };
  }, marker);
}

async function switchToMarkdown(page) {
  const mode = await page.evaluate(() => {
    const proseMirror = document.querySelector(".ProseMirror");
    const quill = document.querySelector(".ql-editor");
    const toggle = document.querySelector(".toggle-mode");
    const toggleText = toggle?.textContent?.trim() || "";
    if (!proseMirror && quill && toggleText.includes("Markdown")) {
      toggle.click();
      return { switched: true };
    }
    return { switched: false, proseMirror: Boolean(proseMirror), quill: Boolean(quill) };
  });

  if (mode.switched) {
    await page.waitForTimeout(500);
    await page.evaluate(() => {
      const confirm = document.querySelector(".confirm");
      confirm?.click();
    });
  }
  await page.waitForSelector(EDITOR_SELECTOR, {
    state: "visible",
    timeout: 15_000,
  });
}

async function dismissRestorePrompt(page) {
  return page.evaluate(() => {
    const button = [...document.querySelectorAll("button, .cancel, .btn")].find(
      (element) => element.textContent?.trim() === "忽略",
    );
    if (!button) return "no popup";
    button.click();
    return "dismissed";
  });
}

export async function stage(options = {}) {
  const articleUrl = options.articleUrl || ARTICLE_URL;
  const bodyJsPath = required(options.bodyJsPath, "bodyJsPath");
  const title = required(options.title, "title");
  const images = options.images || [];
  const task = options.taskSpaceId
    ? await takeOverTaskSpace(options.taskSpaceId)
    : await taskSpace("Stage Zsxq article");
  const page = await articlePage(task);
  const resumed = Boolean(options.taskSpaceId);

  const currentUrl = await page.url();
  if (
    !resumed ||
    !/wx\.zsxq\.com\/(?:article|login)/.test(currentUrl || "")
  ) {
    await page.goto(articleUrl);
  }
  await waitForEditorOrLogin(page);

  const initial = await pageState(page);
  if (initial.login || !initial.title && !initial.proseMirror && !initial.quill) {
    console.log(
      JSON.stringify({
        status: "login_required",
        taskSpaceId: task.spaceId,
        url: initial.url,
        submitted: false,
      }),
    );
    await task.handOff();
    return;
  }
  if (!initial.title) {
    throw new Error(`Zsxq article editor was not detected at ${initial.url}`);
  }

  await switchToMarkdown(page);
  await dismissRestorePrompt(page);
  await page.fill(TITLE_SELECTOR, title);

  const bodyJs = await readFile(bodyJsPath, "utf8");
  const bodyResult = await page.evaluate(bodyJs);
  if (!bodyResult?.success) {
    throw new Error(`Body insertion failed: ${JSON.stringify(bodyResult)}`);
  }

  for (const image of images) {
    const marker = required(image.marker, "image.marker");
    const pasteJsPath = required(image.pasteJsPath, "image.pasteJsPath");
    const deletion = await deleteMarker(page, marker);
    if (!deletion.ok) {
      throw new Error(`Could not delete ${marker}: ${JSON.stringify(deletion)}`);
    }
    await page.waitForTimeout(500);
    const imageJs = await readFile(pasteJsPath, "utf8");
    const imageResult = await page.evaluate(imageJs);
    if (!imageResult?.ok) {
      throw new Error(
        `Image insertion failed for ${marker}: ${JSON.stringify(imageResult)}`,
      );
    }
    await page.waitForTimeout(3_000);
  }

  const verification = await page.evaluate(() => {
    const editor = document.querySelector(".ProseMirror");
    const images = editor
      ? [...editor.querySelectorAll("img:not(.ProseMirror-separator)[src]")]
      : [];
    const text = editor?.textContent || "";
    const markers = text.match(/\[\[IMG_\d+\]\]/g) || [];
    return {
      bodyTextLength: text.length,
      bodyBlockCount: editor?.children.length || 0,
      imageCount: images.length,
      markerCount: markers.length,
    };
  });
  if (
    verification.bodyTextLength < 1 ||
    verification.bodyBlockCount < 1 ||
    verification.markerCount !== 0 ||
    verification.imageCount !== images.length
  ) {
    throw new Error(`ProseMirror verification failed: ${JSON.stringify(verification)}`);
  }

  const screenshotDir = "/tmp/zsxq-article";
  await mkdir(screenshotDir, { recursive: true });
  const screenshotPath = `${screenshotDir}/staged-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });
  console.log(
    JSON.stringify({
      status: "staged",
      taskSpaceId: task.spaceId,
      screenshotPath,
      verification,
      submitted: false,
    }),
  );
  await task.handOff();
}
