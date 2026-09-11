import fs from "node:fs";
import path from "node:path";

function required(value, name) {
  if (!value || !String(value).trim()) throw new Error(`${name} is required`);
  return String(value);
}

async function currentEditorPage(task) {
  const tab = (await task.tabs()).find((item) => item.url?.includes("mp.toutiao.com"));
  if (!tab) throw new Error("Toutiao editor tab not found in the supplied task space");
  return tab.label ? task.page(tab.label) : task.adopt(tab.page);
}

async function visibleControls(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    };
    return [...document.querySelectorAll("button,a,[role=button]")].filter(visible).map((element) => ({
      text: element.textContent?.replace(/\s+/g, " ").trim() ?? "",
      disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
    })).filter((control) => control.text);
  });
}

async function markExactVisibleControl(page, acceptedTexts, attribute) {
  return page.evaluate(({ acceptedTexts, attribute }) => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    };
    const controls = [...document.querySelectorAll("button,a,[role=button]")].filter(visible);
    const match = controls.find((element) => {
      const text = element.textContent?.replace(/\s+/g, " ").trim() ?? "";
      const finalPreview = text === "预览并发布";
      return acceptedTexts.includes(text) && (finalPreview || !/预览|定时|取消/.test(text));
    });
    if (!match) return null;
    match.setAttribute(attribute, "true");
    return match.textContent?.replace(/\s+/g, " ").trim() ?? "";
  }, { acceptedTexts, attribute });
}

export async function submit(options) {
  if (required(options.target, "target") !== "final_publish") {
    throw new Error("target must be exactly final_publish; preview and schedule are never accepted");
  }
  const task = await takeOverTaskSpace(required(options.taskSpaceId, "taskSpaceId"));
  const page = await currentEditorPage(task);
  const beforeUrl = await page.url();
  const controls = await visibleControls(page);
  const initialFinal = await markExactVisibleControl(
    page,
    ["预览并发布", "发布"],
    "data-toutiao-final-target",
  );
  if (!initialFinal) {
    throw new Error(`No visible final publish control found; inspected controls: ${JSON.stringify(controls)}`);
  }
  await page.click("[data-toutiao-final-target]", { label: "open final publish flow" });
  await page.waitForTimeout(1_000);

  const confirmation = await markExactVisibleControl(
    page,
    ["发布"],
    "data-toutiao-final-confirm",
  );
  if (!confirmation) {
    throw new Error("Final publish confirmation was not observable; preview/schedule controls were not clicked");
  }
  await page.click("[data-toutiao-final-confirm]", { label: "confirm final publish" });
  try {
    await page.waitForFunction(
      (oldUrl) => {
        const text = document.body?.innerText ?? "";
        return (
          /发布成功|提交成功|已发布/.test(text) ||
          (location.href !== oldUrl && /article|content|publish|profile_v4/.test(location.href))
        );
      },
      beforeUrl,
      { timeout: 30_000 },
    );
  } catch {
    throw new Error("Final publish was clicked but no observable success state appeared");
  }
  const screenshotDir = "/tmp/toutiao-content-pipeline";
  fs.mkdirSync(screenshotDir, { recursive: true });
  const screenshotPath = path.join(screenshotDir, `published-${Date.now()}.png`);
  await page.screenshot({ path: screenshotPath });
  const result = {
    status: "final_published",
    taskSpaceId: task.spaceId,
    url: await page.url(),
    initialFinalControl: initialFinal,
    confirmationControl: confirmation,
    screenshotPath,
    final_publish_clicked: true,
  };
  console.log(JSON.stringify(result, null, 2));
  await task.finish({ keep: [page.label] });
  return result;
}
