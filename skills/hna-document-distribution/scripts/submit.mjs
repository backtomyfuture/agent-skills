import { mkdir } from "node:fs/promises";

function required(value, name) {
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function viewPage(task) {
  const tab = (await task.tabs()).find((item) =>
    item.url.includes("QueryToView.aspx"),
  );
  if (!tab) throw new Error("Document view tab not found");
  return tab.label ? task.page(tab.label) : task.adopt(tab.page);
}

function distributionTextExpression() {
  return () => {
    const block = [...document.querySelectorAll("div")].find((node) =>
      node.innerText?.includes("分发信息") && node.innerText.length < 4000,
    );
    return (block?.innerText || document.body.innerText)
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 1500);
  };
}

export async function submit({ taskSpaceId }) {
  const task = await takeOverTaskSpace(required(taskSpaceId, "taskSpaceId"));
  const page = await viewPage(task);
  const before = await page.evaluate(() => {
    const value = (id) => document.querySelector(`#${id}`)?.value || "";
    const block = [...document.querySelectorAll("div")].find((node) =>
      node.innerText?.includes("分发信息") && node.innerText.length < 4000,
    );
    return {
      recId: value("UcAllotAdv1_UcReceiverSel1_txbRecID"),
      allRec: value("UcAllotAdv1_UcReceiverSel1_txbAllRec"),
      distribution: (block?.innerText || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 1500),
      subed: window.subed === true,
    };
  });
  if (!before.recId) throw new Error("Recipient is not selected");
  if (before.subed) throw new Error("This document already has a submit in flight");

  const receipt = await page.click("#UcAllotAdv1_btDocAllot", {
    label: "distribute document",
  });
  let dialogText = receipt.dialog?.message || "";
  if (!dialogText && (await page.info()).dialog) {
    dialogText = (await page.info()).dialog?.message || "";
  }
  if (dialogText.includes("重复提交")) {
    await page.dismissDialog().catch(() => {});
    throw new Error("Portal blocked a repeated submit");
  }
  if (dialogText.includes("密级")) {
    await page.acceptDialog();
  } else if (dialogText) {
    await page.dismissDialog().catch(() => {});
    throw new Error(`Unexpected dialog: ${dialogText}`);
  }

  await page
    .waitForFunction(
      (previous) => {
        const block = [...document.querySelectorAll("div")].find((node) =>
          node.innerText?.includes("分发信息") && node.innerText.length < 4000,
        );
        const current = (block?.innerText || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 1500);
        return current && current !== previous;
      },
      before.distribution,
      { timeout: 25_000 },
    )
    .catch(() => false);

  const after = await page.evaluate(distributionTextExpression());
  const changed = after !== before.distribution;
  const screenshotDir = "/tmp/hna-document-distribution";
  await mkdir(screenshotDir, { recursive: true });
  const screenshotPath = `${screenshotDir}/submit-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });
  console.log(
    JSON.stringify({
      status: changed ? "submitted" : "needs_review",
      taskSpaceId: task.spaceId,
      recipient: before.allRec,
      url: await page.url(),
      title: await page.title(),
      screenshotPath,
      submitted: changed,
    }),
  );
  if (!changed) {
    await task.handOff();
    return;
  }
  await task.finish({ keep: [page.label] });
}
