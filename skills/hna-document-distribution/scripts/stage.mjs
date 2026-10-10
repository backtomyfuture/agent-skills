import { mkdir } from "node:fs/promises";

const INDEX_URL = "http://oa3.hnair.net/oawebapp/index.aspx";
const CATEGORIES = {
  我呈报的公文: "0701",
  分发给我的公文: "0702",
  本人签发过的公文: "0703",
  抄报给我的公文: "0707",
  阅知公文: "0709",
};

function required(value, name) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} is required`);
  }
  return String(value).trim();
}

function accountToken(account) {
  const bare = String(account).trim().replace(/^\[|\]$/g, "");
  if (!bare) throw new Error("account is empty");
  return `[${bare}]`;
}

async function indexPage(task) {
  const tab = (await task.tabs()).find((item) =>
    item.url.includes("oawebapp/index.aspx"),
  );
  if (tab) return tab.label ? task.page(tab.label) : task.adopt(tab.page);
  return task.page("p1");
}

async function waitForQueryLink(page) {
  return page
    .waitForFunction(
      () =>
        [...document.querySelectorAll("a")].some(
          (link) => link.textContent?.trim() === "公文查询",
        ),
      undefined,
      { timeout: 12_000 },
    )
    .then(() => true)
    .catch(() => false);
}

async function ensureQueryForm(page) {
  const ready = await page
    .waitForFunction(
      () =>
        Boolean(
          document.querySelector("iframe")?.contentDocument?.querySelector(
            "#ibtQuerySubmit",
          ),
        ),
      undefined,
      { timeout: 2_000 },
    )
    .then(() => true)
    .catch(() => false);
  if (ready) return;

  await page.evaluate(() => {
    const link = [...document.querySelectorAll("a")].find(
      (item) => item.textContent?.trim() === "公文查询",
    );
    if (!link) throw new Error("公文查询 link missing");
    link.id = "hnaOpenQuery";
  });
  await page.click("#hnaOpenQuery", { label: "open document query" });
  await page.waitForFunction(
    () =>
      Boolean(
        document.querySelector("iframe")?.contentDocument?.querySelector(
          "#ibtQuerySubmit",
        ),
      ),
    undefined,
    { timeout: 15_000 },
  );
}

function report(payload) {
  console.log(JSON.stringify(payload));
}

export async function stage(options) {
  const docId = options.docId ? String(options.docId).trim() : "";
  const title = options.title ? String(options.title).trim() : "";
  if (!docId && !title) throw new Error("docId or title is required");
  const recipientName = required(options.recipientName, "recipientName");
  const account = options.account ? accountToken(options.account) : "";
  const department = options.department ? String(options.department).trim() : "";
  const category = options.category ?? "我呈报的公文";
  if (!CATEGORIES[category]) {
    throw new Error(`Unknown category: ${category}`);
  }
  const year = String(options.year ?? new Date().getFullYear());
  const submitTime = options.submitTime ? String(options.submitTime).trim() : "";

  const task = options.taskSpaceId
    ? await takeOverTaskSpace(options.taskSpaceId)
    : await taskSpace("Stage HNA document distribution");
  const page = await indexPage(task);

  if (!(await waitForQueryLink(page))) {
    await page.goto(INDEX_URL);
  }
  if (!(await waitForQueryLink(page))) {
    report({
      status: "login_required",
      taskSpaceId: task.spaceId,
      url: await page.url(),
    });
    await task.handOff();
    return;
  }

  await ensureQueryForm(page);
  await page.evaluate(
    ({ docId: id, title: titleText, year: queryYear, categoryValue }) => {
      const doc = document.querySelector("iframe")?.contentDocument;
      if (!doc) throw new Error("Query iframe missing");
      const titleInput = doc.querySelector("#txtTitle");
      const idInput = doc.querySelector("#txtDocId");
      const yearSelect = doc.querySelector("#SelDate1_SelYear");
      const direction = doc.querySelector("#ddlDocDirection");
      if (!titleInput || !idInput || !yearSelect || !direction) {
        throw new Error("Query form controls missing");
      }
      titleInput.value = titleText;
      idInput.value = id;
      yearSelect.value = queryYear;
      direction.value = categoryValue;
    },
    { docId, title, year, categoryValue: CATEGORIES[category] },
  );
  await page.evaluate(() => {
    const button = document
      .querySelector("iframe")
      ?.contentDocument?.querySelector("#ibtQuerySubmit");
    if (!button) throw new Error("Query button missing");
    button.click();
  });
  await page.waitForFunction(
    () => {
      const table = document
        .querySelector("iframe")
        ?.contentDocument?.querySelector("#tgDocQuery");
      return Boolean(table?.querySelector("a"));
    },
    undefined,
    { timeout: 20_000 },
  );

  const matches = await page.evaluate(
    ({ title: titleText, submitTime: wantedTime }) => {
      const doc = document.querySelector("iframe").contentDocument;
      return [...doc.querySelectorAll("#tgDocQuery tr")]
        .slice(1)
        .map((row) => {
          const cells = [...row.querySelectorAll("td")].map((cell) =>
            cell.innerText.trim().replace(/\s+/g, " "),
          );
          const link = row.querySelector("a");
          return {
            title: link?.innerText?.trim() || cells[3] || "",
            submitTime: cells[5] || "",
            href: link?.getAttribute("href") || "",
          };
        })
        .filter((row) => row.href.includes("OpenHQNewShow"))
        .filter((row) => !titleText || row.title === titleText)
        .filter((row) => !wantedTime || row.submitTime === wantedTime);
    },
    { title, submitTime },
  );

  if (matches.length !== 1) {
    report({
      status: "ambiguous",
      taskSpaceId: task.spaceId,
      reason: matches.length === 0 ? "no_document" : "multiple_documents",
      matches: matches.map(({ title: rowTitle, submitTime: rowTime }) => ({
        title: rowTitle,
        submitTime: rowTime,
      })),
    });
    await task.handOff();
    return;
  }

  const iframeUrl = await page.evaluate(
    () => document.querySelector("iframe").contentWindow.location.href,
  );
  const relative = matches[0].href.match(/OpenHQNewShow\('([^']+)'\)/)?.[1];
  if (!relative) throw new Error("Document view URL missing");
  const viewUrl = new URL(relative, iframeUrl).href;
  const view = await task.newPage();
  await view.goto(viewUrl);
  await view.waitForSelector("#UcAllotAdv1_UcReceiverSel1_txbRecName", {
    state: "visible",
    timeout: 20_000,
  });

  const openedDocId = await view.evaluate(() => {
    const match = document.body.innerText.match(/办文编号：\s*(\d+)/);
    return match?.[1] || "";
  });
  if (docId && openedDocId !== docId) {
    throw new Error(`Opened 办文编号 ${openedDocId}, expected ${docId}`);
  }

  await view.evaluate(() => {
    const input = document.querySelector("#UcAllotAdv1_UcReceiverSel1_txbRecName");
    input.focus();
    input.value = "";
    input.dispatchEvent(
      new KeyboardEvent("keydown", { keyCode: 65, which: 65, bubbles: true }),
    );
  });
  await view.waitForTimeout(800);
  await view.evaluate((term) => {
    const input = document.querySelector("#UcAllotAdv1_UcReceiverSel1_txbRecName");
    input.focus();
    input.value = term;
    input.dispatchEvent(
      new KeyboardEvent("keydown", { keyCode: 65, which: 65, bubbles: true }),
    );
  }, recipientName);
  await view.waitForFunction(
    (term) => {
      const box = document.querySelector(".ac_results");
      return Boolean(
        box &&
          getComputedStyle(box).display !== "none" &&
          [...box.querySelectorAll("li")].some((item) =>
            item.innerText.includes(term),
          ),
      );
    },
    recipientName,
    { timeout: 8_000 },
  );

  const suggestions = await view.evaluate(() =>
    [...document.querySelectorAll(".ac_results li")].map((item, index) => ({
      index,
      text: item.innerText.replace(/\s+/g, " ").trim(),
    })),
  );
  const hits = suggestions.filter((item) => {
    if (account && !item.text.includes(account)) return false;
    if (department && !item.text.includes(department)) return false;
    if (!account && !department && suggestions.length > 1) return false;
    return item.text.includes(recipientName);
  });
  if (hits.length !== 1) {
    report({
      status: "ambiguous",
      taskSpaceId: task.spaceId,
      reason: "ambiguous_recipient",
      suggestions,
    });
    await task.handOff();
    return;
  }

  await view.evaluate((index) => {
    const item = document.querySelectorAll(".ac_results li")[index];
    item.id = "hnaPickRecipient";
  }, hits[0].index);
  await view.click("#hnaPickRecipient", { label: "select recipient" });
  await view.waitForFunction(
    () => Boolean(document.querySelector("#UcAllotAdv1_UcReceiverSel1_txbRecID")?.value),
    undefined,
    { timeout: 5_000 },
  );

  const verification = await view.evaluate((expected) => {
    const value = (id) => document.querySelector(`#${id}`)?.value || "";
    const distributed = document.body.innerText.includes("已分发人员")
      ? (document.body.innerText.match(/已分发人员[\s\S]{0,400}/) || [""])[0]
      : "";
    return {
      name: value("UcAllotAdv1_UcReceiverSel1_txbRecName"),
      recId: value("UcAllotAdv1_UcReceiverSel1_txbRecID"),
      allRec: value("UcAllotAdv1_UcReceiverSel1_txbAllRec"),
      organId: value("UcAllotAdv1_UcReceiverSel1_HidOrganID"),
      suggestVisible:
        document.querySelector(".ac_results") &&
        getComputedStyle(document.querySelector(".ac_results")).display !== "none",
      alreadyDistributed: expected.account
        ? distributed.includes(expected.account.replace(/[[\]]/g, ""))
        : distributed.includes(expected.recipientName),
    };
  }, { account, recipientName });

  if (
    !verification.recId ||
    !verification.organId ||
    verification.suggestVisible ||
    (account && !verification.allRec.includes(account.replace(/[[\]]/g, "")))
  ) {
    throw new Error(`Recipient verification failed: ${JSON.stringify(verification)}`);
  }

  const screenshotDir = "/tmp/hna-document-distribution";
  await mkdir(screenshotDir, { recursive: true });
  const screenshotPath = `${screenshotDir}/filled-${Date.now()}.png`;
  await view.screenshot({ path: screenshotPath });
  report({
    status: "filled_preview",
    taskSpaceId: task.spaceId,
    page: view.label,
    docId: openedDocId,
    title: matches[0].title,
    submitTime: matches[0].submitTime,
    verification,
    screenshotPath,
    submitted: false,
  });
  await task.handOff();
}
