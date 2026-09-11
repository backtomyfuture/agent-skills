function required(value, name) {
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function isResultPageUrl(url) {
  return /Trace|Track|DocFollow|MyDoc|WorkDoc/i.test(url);
}

async function formPage(task) {
  const tab = (await task.tabs()).find((item) =>
    item.url.includes("LeaveApplicationLink.aspx"),
  );
  if (!tab) throw new Error("Leave-application form tab not found");
  return tab.label ? task.page(tab.label) : task.adopt(tab.page);
}

export async function submit({ taskSpaceId }) {
  const task = await takeOverTaskSpace(required(taskSpaceId, "taskSpaceId"));
  const page = await formPage(task);
  const alreadySubmitted = await page.evaluate(() => {
    return (
      performance
        .getEntriesByType("resource")
        .some((entry) => entry.name.includes("savemyapply"))
    );
  });
  if (alreadySubmitted) throw new Error("This form was already submitted");

  await page.evaluate(() => {
    if (window.__hnaSubmitInFlight === true) {
      throw new Error("This form submission is already in progress");
    }
    if (typeof window.checkFormMain !== "function") {
      throw new Error("checkFormMain is unavailable");
    }
    window.__hnaSubmitInFlight = true;
    window.checkFormMain();
  });

  try {
    await page.waitForFunction(
      () => {
        return (
          /Trace|Track|DocFollow|MyDoc|WorkDoc/i.test(location.href) &&
          document.readyState === "complete"
        );
      },
      undefined,
      { timeout: 30_000 },
    );
  } catch (error) {
    const posted = await page.evaluate(() =>
      performance
        .getEntriesByType("resource")
        .some((entry) => entry.name.includes("savemyapply")),
    );
    if (!posted) {
      await page.evaluate(() => {
        window.__hnaSubmitInFlight = false;
      });
    }
    throw error;
  }

  const result = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    text: document.body.innerText.replace(/\s+/g, " ").trim().slice(0, 500),
  }));
  if (!isResultPageUrl(result.url)) {
    throw new Error(`Unexpected result page: ${result.url}`);
  }
  const screenshotPath = `/tmp/hna-leave-application/submitted-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });

  console.log(
    JSON.stringify({
      status: "submitted",
      result,
      screenshotPath,
      submitted: true,
    }),
  );
  await task.finish({ keep: [page.label] });
}
