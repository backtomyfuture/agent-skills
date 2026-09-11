import fs from "node:fs";
import path from "node:path";

const EDITORS = {
  article: "https://mp.toutiao.com/profile_v4/graphic/publish",
  weitoutiao: "https://mp.toutiao.com/profile_v4/weitoutiao/publish",
};

function required(value, name) {
  if (!value || !String(value).trim()) throw new Error(`${name} is required`);
  return String(value);
}

function payloadFrom(file) {
  const payloadPath = path.resolve(file);
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
  const bodyFile = path.isAbsolute(payload.body_file)
    ? payload.body_file
    : path.resolve(path.dirname(payloadPath), payload.body_file);
  if (!fs.existsSync(bodyFile)) throw new Error(`body_file not found: ${bodyFile}`);
  for (const image of payload.images ?? []) {
    if (image.resolved_path && !fs.existsSync(image.resolved_path)) {
      throw new Error(`image missing: ${image.resolved_path}`);
    }
  }
  return { ...payload, payloadPath, bodyFile };
}

function textToHtml(text) {
  return (
    text
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => (line.trim() ? `<p>${escapeHtml(line)}</p>` : "<p><br></p>"))
      .join("") || "<p><br></p>"
  );
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function editorPage(task, editorUrl) {
  return task.tabs().then((tabs) => {
    const tab = tabs.find((item) => item.url?.includes("mp.toutiao.com"));
    return tab ? (tab.label ? task.page(tab.label) : task.adopt(tab.page)) : task.page("p1");
  }).then(async (page) => {
    if (!(await page.url()).includes("mp.toutiao.com")) await page.goto(editorUrl);
    const currentUrl = await page.url();
    const expectedPath = editorUrl.includes("weitoutiao")
      ? "/weitoutiao/publish"
      : "/graphic/publish";
    if (!currentUrl.includes(expectedPath)) await page.goto(editorUrl);
    return page;
  });
}

async function pageState(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    };
    const text = document.body?.innerText ?? "";
    const title = document.querySelector(
      "textarea[placeholder*='请输入文章标题'], input[placeholder*='请输入文章标题']",
    );
    const editor = document.querySelector(".syl-editor, .ProseMirror, [contenteditable='true']");
    const login = [...document.querySelectorAll("button,a,[role=button]")].some(
      (element) => visible(element) && /登录|扫码登录|手机号登录|立即登录/.test(element.textContent ?? ""),
    );
    return {
      url: location.href,
      title: Boolean(title),
      editor: Boolean(editor),
      login: login || /登录后|请登录|扫码登录/.test(text),
    };
  });
}

async function waitForEditorOrLogin(page) {
  try {
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText ?? "";
        return Boolean(
          document.querySelector(
            "textarea[placeholder*='请输入文章标题'], input[placeholder*='请输入文章标题'], .syl-editor, .ProseMirror, [contenteditable='true']",
          ),
        ) || /登录后|请登录|扫码登录|手机号登录/.test(text);
      },
      undefined,
      { timeout: 15_000 },
    );
  } catch {
    // pageState below turns an unknown/slow page into a safe login handoff.
  }
  return pageState(page);
}

async function setTitleAndBody(page, title, bodyHtml) {
  return page.evaluate(
    ({ title, bodyHtml }) => {
      const titleEl = document.querySelector(
        "textarea[placeholder*='请输入文章标题'], input[placeholder*='请输入文章标题']",
      );
      if (!titleEl) throw new Error("Toutiao title input not found");
      const valueSetter = Object.getOwnPropertyDescriptor(
        titleEl instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype,
        "value",
      )?.set;
      valueSetter?.call(titleEl, title);
      titleEl.dispatchEvent(new Event("input", { bubbles: true }));
      titleEl.dispatchEvent(new Event("change", { bubbles: true }));

      const host = document.querySelector(".syl-editor");
      const editorKey =
        host &&
        Reflect.ownKeys(host).map(String).find((key) =>
          /^__react(Fiber|InternalInstance)/.test(key),
        );
      let cursor = editorKey ? host[editorKey] : null;
      let editor = null;
      for (let depth = 0; cursor && depth < 12; depth += 1) {
        if (cursor.stateNode?.editor) {
          editor = cursor.stateNode.editor;
          break;
        }
        cursor = cursor.return;
      }
      if (!editor) throw new Error("Toutiao ProseMirror editor instance not found");
      editor.setHTML(bodyHtml);
      const text = editor.getText();
      const html = editor.getHTML();
      return {
        title: titleEl.value,
        textLen: text.length,
        textStart: text.slice(0, 120),
        textEnd: text.slice(-180),
        imageTags: (html.match(/<img\b/g) ?? []).length,
        markerCount: (text.match(/\[\[IMG_\d+\]\]/g) ?? []).length,
      };
    },
    { title, bodyHtml },
  );
}

async function selectMarker(page, marker) {
  return page.evaluate((marker) => {
    const host = document.querySelector(".syl-editor");
    const editorKey =
      host &&
      Reflect.ownKeys(host).map(String).find((key) => /^__react(Fiber|InternalInstance)/.test(key));
    let cursor = editorKey ? host[editorKey] : null;
    let editor = null;
    for (let depth = 0; cursor && depth < 12; depth += 1) {
      if (cursor.stateNode?.editor) {
        editor = cursor.stateNode.editor;
        break;
      }
      cursor = cursor.return;
    }
    if (!editor) throw new Error("Toutiao ProseMirror editor instance not found");
    let found = null;
    editor.view.state.doc.descendants((node, pos) => {
      if (found || !node.isText || !node.text) return !found;
      const index = node.text.indexOf(marker);
      if (index >= 0) found = { from: pos + index, to: pos + index + marker.length };
      return !found;
    });
    if (!found) return { ok: false, marker };
    const Selection = editor.view.state.selection.constructor;
    editor.view.dispatch(
      editor.view.state.tr
        .setSelection(Selection.create(editor.view.state.doc, found.from, found.to))
        .scrollIntoView(),
    );
    editor.view.focus();
    return { ok: true, marker };
  }, marker);
}

async function editorStats(page) {
  return page.evaluate(() => {
    const host = document.querySelector(".syl-editor");
    const editorKey =
      host &&
      Reflect.ownKeys(host).map(String).find((key) => /^__react(Fiber|InternalInstance)/.test(key));
    let cursor = editorKey ? host[editorKey] : null;
    let editor = null;
    for (let depth = 0; cursor && depth < 12; depth += 1) {
      if (cursor.stateNode?.editor) {
        editor = cursor.stateNode.editor;
        break;
      }
      cursor = cursor.return;
    }
    if (editor) {
      const text = editor.getText();
      const html = editor.getHTML();
      return {
        text,
        html,
        textLen: text.length,
        imageTags: (html.match(/<img\b/g) ?? []).length,
        markers: (text.match(/\[\[IMG_\d+\]\]/g) ?? []).length,
      };
    }
    const fallback = document.querySelector(".ProseMirror, [contenteditable='true']");
    return {
      text: fallback?.innerText ?? "",
      html: fallback?.innerHTML ?? "",
      textLen: (fallback?.innerText ?? "").length,
      imageTags: fallback?.querySelectorAll("img").length ?? 0,
      markers: (fallback?.innerText?.match(/\[\[IMG_\d+\]\]/g) ?? []).length,
    };
  });
}

async function confirmImageDialog(page) {
  await page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    };
    const button = [...document.querySelectorAll("button,[role=button],a")].find(
      (element) =>
        visible(element) &&
        /^(确定|插入图片|上传)$/.test(element.textContent?.trim() ?? ""),
    );
    if (button) button.setAttribute("data-toutiao-image-confirm", "true");
  });
  try {
    await page.click("[data-toutiao-image-confirm]", { label: "confirm image upload" });
  } catch {
    // Some editor versions insert immediately after the file chooser closes.
  }
}

async function uploadImage(page, image) {
  const marker = required(image.marker, "image.marker");
  const file = required(image.resolved_path, `${marker}.resolved_path`);
  const selected = await selectMarker(page, marker);
  if (!selected.ok) return { marker, path: file, status: "marker_not_found" };
  const before = await editorStats(page);
  let uploaded = false;
  try {
    const chooserPromise = page.waitForFileChooser({ timeout: 8_000 });
    await page.click(
      ".syl-toolbar-tool.image button, button[aria-label*='图片'], button[title*='图片']",
      { label: "open inline image picker" },
    );
    const chooser = await chooserPromise;
    await chooser.setFiles(file);
    uploaded = true;
  } catch {
    // Fall back to the page-level file-input API when this editor version does
    // not expose a filechooser event.
    for (const selector of [
      "input[type=file][accept*=image]",
      "input[type=file]",
    ]) {
      try {
        await page.setInputFiles(selector, [file]);
        uploaded = true;
        break;
      } catch {
        // Try the next editor-specific input shape.
      }
    }
  }
  await confirmImageDialog(page);
  await page.waitForTimeout(2_000);
  const after = await editorStats(page);
  return {
    marker,
    path: file,
    status: uploaded && after.imageTags > before.imageTags ? "uploaded" : "not_confirmed",
    imageTagsBefore: before.imageTags,
    imageTagsAfter: after.imageTags,
  };
}

function samplesFor(body) {
  const clean = body.replace(/\[\[IMG_\d+\]\]/g, "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  const middle = Math.max(0, Math.floor(clean.length / 2) - 30);
  return [...new Set([
    clean.slice(0, Math.min(50, clean.length)),
    clean.slice(middle, middle + Math.min(60, clean.length - middle)),
    clean.slice(-Math.min(70, clean.length)),
  ])].filter(Boolean);
}

async function verify(page, payload, body) {
  const expectedSamples = samplesFor(body);
  const stats = await editorStats(page);
  const checks = await page.evaluate(
    ({ title, samples }) => {
      const titleEl = document.querySelector(
        "textarea[placeholder*='请输入文章标题'], input[placeholder*='请输入文章标题']",
      );
      const host = document.querySelector(".syl-editor");
      const editorKey =
        host &&
        Reflect.ownKeys(host).map(String).find((key) => /^__react(Fiber|InternalInstance)/.test(key));
      let cursor = editorKey ? host[editorKey] : null;
      let editor = null;
      for (let depth = 0; cursor && depth < 12; depth += 1) {
        if (cursor.stateNode?.editor) {
          editor = cursor.stateNode.editor;
          break;
        }
        cursor = cursor.return;
      }
      const text = editor?.getText?.() ?? document.querySelector(".ProseMirror, [contenteditable='true']")?.innerText ?? "";
      return {
        titleMatches: titleEl?.value === title,
        samples: samples.map((sample) => ({ sample, present: text.includes(sample) })),
        textLen: text.length,
        imageCount: editor ? (editor.getHTML().match(/<img\b/g) ?? []).length : document.querySelectorAll("img").length,
        sourceEndingPresent: /参考来源|参考资料/.test(text),
      };
    },
    { title: payload.title, samples: expectedSamples },
  );
  return {
    expectedBodyChars: body.length,
    editorTextChars: checks.textLen,
    titleMatches: checks.titleMatches,
    bodySamples: checks.samples,
    allSamplesPresent: checks.samples.every((sample) => sample.present),
    imageCount: checks.imageCount,
    sourceEndingPresent: checks.sourceEndingPresent,
    initialSet: stats,
  };
}

export async function stage(options) {
  const payload = payloadFrom(required(options.payloadPath, "payloadPath"));
  const mode = payload.mode === "weitoutiao" ? "weitoutiao" : "article";
  const editorUrl = EDITORS[mode];
  const body = fs.readFileSync(payload.bodyFile, "utf8");
  const task = options.taskSpaceId
    ? await takeOverTaskSpace(options.taskSpaceId)
    : await taskSpace(`Toutiao ${mode} staging`);
  const page = await editorPage(task, editorUrl);
  const state = await waitForEditorOrLogin(page);
  if (!state.title || !state.editor) {
    const result = {
      status: "login_required",
      taskSpaceId: task.spaceId,
      url: state.url,
      final_publish_clicked: false,
    };
    console.log(JSON.stringify(result, null, 2));
    await task.handOff();
    return result;
  }

  const initial = await setTitleAndBody(page, payload.title, textToHtml(body));
  const imageResults = [];
  for (const image of payload.images ?? []) {
    imageResults.push(await uploadImage(page, image));
  }
  const verification = await verify(page, payload, body);
  const expectedImages = (payload.images ?? []).length;
  const imageUploadsConfirmed = imageResults.every(
    (result) => result.status === "uploaded",
  );
  if (
    !verification.titleMatches ||
    !verification.allSamplesPresent ||
    !imageUploadsConfirmed ||
    verification.imageCount !== expectedImages
  ) {
    throw new Error(`Toutiao editor verification failed: ${JSON.stringify(verification)}`);
  }
  const screenshotDir = "/tmp/toutiao-content-pipeline";
  fs.mkdirSync(screenshotDir, { recursive: true });
  const screenshotPath = path.join(
    screenshotDir,
    `staged-${Date.now()}-${mode}.png`,
  );
  await page.screenshot({ path: screenshotPath });
  const result = {
    status: "staged_autosaved",
    taskSpaceId: task.spaceId,
    url: await page.url(),
    mode,
    title: payload.title,
    bodyChars: payload.body_chars ?? body.length,
    imageResults,
    verification: { initial, ...verification },
    screenshotPath,
    final_publish_clicked: false,
  };
  console.log(JSON.stringify(result, null, 2));
  await task.handOff();
  return result;
}
