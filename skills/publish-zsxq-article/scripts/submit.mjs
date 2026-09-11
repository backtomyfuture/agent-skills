const TITLE_SELECTOR = 'input[placeholder="请在这里输入标题"]';
const ARTICLE_PATTERN = /wx\.zsxq\.com\/article/;

function required(value, name) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} is required`);
  }
  return String(value);
}

async function articlePage(task) {
  const tab = (await task.tabs()).find((item) =>
    ARTICLE_PATTERN.test(item.url || ""),
  );
  if (!tab) throw new Error("Zsxq article tab not found in the task space");
  return tab.label ? task.page(tab.label) : task.adopt(tab.page);
}

async function enableSchedule(page) {
  const state = await page.evaluate(() => {
    const timer = document.querySelector(".scheduled-topic-timer");
    const input = timer?.querySelector("input[type=checkbox]");
    const label = timer?.querySelector("label.green");
    return {
      enabled: Boolean(
        input?.checked ||
          timer?.classList.contains("active") ||
          label?.classList.contains("active"),
      ),
      hasToggle: Boolean(label),
    };
  });
  if (!state.hasToggle) throw new Error("Zsxq schedule switch not found");
  if (!state.enabled) {
    await page.click(".scheduled-topic-timer label.green", {
      label: "enable scheduled publishing",
    });
  }
  await page.waitForSelector(".scheduled-topic-timer #date.flatpickr-input", {
    state: "visible",
    timeout: 10_000,
  });
}

async function setTomorrowAtTen(page) {
  return page.evaluate(() => {
    const tomorrow = new Date(Date.now() + 86_400_000);
    const dateString = [
      tomorrow.getFullYear(),
      String(tomorrow.getMonth() + 1).padStart(2, "0"),
      String(tomorrow.getDate()).padStart(2, "0"),
    ].join("/");
    const input = document.querySelector(
      ".scheduled-topic-timer #date.flatpickr-input",
    );
    const flatpickr = input?._flatpickr;
    if (!flatpickr) return { ok: false, reason: "flatpickr not found" };
    flatpickr.setDate(dateString, true, "Y/m/d");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));

    const boxes = [
      ...document.querySelectorAll(".scheduled-topic-timer app-topic-timer .time"),
    ];
    if (boxes.length < 2) return { ok: false, reason: "time boxes not found" };

    const pick = (box, expected, alternate) => {
      const item = [...box.querySelectorAll("li")].find((li) => {
        const text = li.textContent?.trim();
        return text === expected || text === alternate;
      });
      if (!item) return null;
      item.click();
      return item.textContent.trim();
    };
    const hour = pick(boxes[0], "10");
    const minute = pick(boxes[1], "00", "0");
    if (!hour || !minute) {
      return { ok: false, reason: "10:00 option not found", date: input.value };
    }
    return {
      ok: true,
      date: input.value,
      hour,
      minute,
      scheduled: `${dateString} ${hour}:${minute}`,
    };
  });
}

async function waitForScheduleSuccess(page) {
  return page.waitForFunction(
    () => {
      const visibleText = document.body?.innerText || "";
      const messages = [
        ...document.querySelectorAll(
          ".toast, .el-message, .ant-message, .layui-layer, [role=alert]",
        ),
      ].map((element) => element.textContent || "");
      return /定时发布成功|已定时发布|文章已发布|发布成功/.test(
        `${visibleText}\n${messages.join("\n")}`,
      );
    },
    undefined,
    { timeout: 10_000 },
  );
}

export async function submit({ taskSpaceId } = {}) {
  const task = await takeOverTaskSpace(required(taskSpaceId, "taskSpaceId"));
  const page = await articlePage(task);
  const current = await page.evaluate((titleSelector) => ({
    url: location.href,
    login: /\/login(?:[/?#]|$)/.test(location.pathname),
    editor: Boolean(document.querySelector(titleSelector)),
  }), TITLE_SELECTOR);
  if (current.login || !current.editor) {
    throw new Error(`Zsxq article editor is not ready at ${current.url}`);
  }

  await enableSchedule(page);
  const scheduled = await setTomorrowAtTen(page);
  if (!scheduled.ok) throw new Error(JSON.stringify(scheduled));

  const buttonText = await page.evaluate(() =>
    document.querySelector(".operation-btns .post.btn")?.textContent?.trim() || "",
  );
  if (buttonText !== "定时发布") {
    throw new Error(
      `Refusing to click publish button with text ${JSON.stringify(buttonText)}`,
    );
  }

  await page.click(".operation-btns .post.btn", {
    label: "confirm scheduled publishing",
  });
  try {
    await waitForScheduleSuccess(page);
  } catch {
    const result = await page.evaluate(() => ({
      url: location.href,
      text: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 500),
    }));
    console.log(
      JSON.stringify({
        status: "click_sent_unverified",
        scheduled,
        result,
        submitted: false,
      }),
    );
    throw new Error(
      "Scheduled-publish click was sent, but success was not observable; not retrying",
    );
  }

  const result = await page.evaluate(() => ({
    url: location.href,
    text: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 500),
  }));
  console.log(
    JSON.stringify({
      status: "scheduled",
      scheduled,
      result,
      submitted: true,
    }),
  );
  await task.finish({ keep: [page.label] });
}
