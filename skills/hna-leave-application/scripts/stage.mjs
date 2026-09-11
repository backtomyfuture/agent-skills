const FORM_URL =
  "http://hr.hna.net/ehr/NewHomePage/EmployeeBenefits/LeaveApplicationLink.aspx";

function required(value, name) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} is required`);
  }
  return String(value);
}

function formatAdvice({ greeting = "各位领导，", body, attachmentLabel }) {
  const lines = required(body, "adviceBody")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => `    ${line}`);
  return [greeting, ...lines, `附件：${attachmentLabel}`].join("\n");
}

async function formPage(task) {
  const tab = (await task.tabs()).find((item) =>
    item.url.includes("LeaveApplicationLink.aspx"),
  );
  if (tab) {
    return tab.label ? task.page(tab.label) : task.adopt(tab.page);
  }
  return task.page("p1");
}

async function waitForForm(page) {
  return page
    .waitForFunction(
      () =>
        location.href.includes("LeaveApplicationLink.aspx") &&
        Boolean(document.querySelector("#btnFixedFlow")),
      undefined,
      { timeout: 15_000 },
    )
    .then(() => true)
    .catch(() => false);
}

export async function stage(options) {
  const attachmentPath = required(options.attachmentPath, "attachmentPath");
  const attachmentLabel =
    options.attachmentLabel ??
    attachmentPath.split("/").pop().replace(/\.[^.]+$/, "");
  const input = {
    leaveType: required(options.leaveType, "leaveType"),
    flowName: required(options.flowName, "flowName"),
    begin: required(options.beginDate, "beginDate"),
    end: required(options.endDate, "endDate"),
    period: options.period ?? "全天",
    reason: options.reason ?? "个人原因。",
    handover: options.handover ?? "工作自带。",
    advice: formatAdvice({
      greeting: options.greeting,
      body: options.adviceBody,
      attachmentLabel,
    }),
    attachmentName: attachmentPath.split("/").pop(),
  };

  const task = options.taskSpaceId
    ? await takeOverTaskSpace(options.taskSpaceId)
    : await taskSpace("Stage HNA leave application");
  const page = await formPage(task);

  if (!(await waitForForm(page))) {
    await page.goto(FORM_URL);
  }

  if (!(await waitForForm(page))) {
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

  const popupPromise = page.waitForEvent("popup", { timeout: 10_000 });
  await page.click("#btnFixedFlow", { label: "open approval flow" });
  const popup = await popupPromise;
  await popup.waitForFunction(
    (flowName) =>
      [...document.querySelectorAll("a")].some(
        (link) => link.textContent?.trim() === flowName,
      ),
    input.flowName,
    { timeout: 20_000 },
  );

  const found = await popup.evaluate((flowName) => {
    for (const row of document.querySelectorAll("tr")) {
      const name = row.querySelector("a")?.textContent?.trim();
      if (name !== flowName) continue;
      const pick = [...row.querySelectorAll("a")].find(
        (link) => link.textContent?.trim() === "选择",
      );
      if (pick) {
        pick.id = "hnaPickFlow";
        return true;
      }
    }
    return false;
  }, input.flowName);
  if (!found) throw new Error(`Flow not found: ${input.flowName}`);

  const pickReceipt = await popup.click("#hnaPickFlow", {
    label: "select approval flow",
  });
  if (!pickReceipt.dialog) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await popup.waitForTimeout(500);
      if ((await popup.info()).dialog) break;
    }
  }
  if ((await popup.info()).dialog) {
    await popup.acceptDialog();
  }
  await page.waitForFunction(
    () => Boolean(document.querySelector("#hdFixedFlow")?.value),
    undefined,
    { timeout: 20_000 },
  );

  await page.setInputFiles("input[name=filedata]", [attachmentPath]);
  await page.waitForFunction(
    (attachmentName) =>
      [...document.querySelectorAll("td")].some(
        (cell) => cell.textContent?.trim() === attachmentName,
      ),
    input.attachmentName,
    { timeout: 15_000 },
  );
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll(".layui-layer-content")].some((layer) =>
        layer.textContent?.includes("上传中"),
      ),
    undefined,
    { timeout: 30_000 },
  );

  await page.evaluate((values) => {
    const $ = window.jQuery;
    if (!$) throw new Error("jQuery is unavailable");

    $(".tbType").each(function () {
      const select = this;
      $(select)
        .find("option")
        .each(function () {
          if ($(this).text().trim() === values.leaveType) {
            $(this).prop("selected", true);
          }
        });
      $(select).trigger("change");
    });

    $(".tbBeginDate").val(values.begin);
    $(".tbEndDate").val(values.end);
    if (typeof window.WdPicker === "function") {
      window.WdPicker.call($(".tbEndDate")[0]);
    }

    if (values.period !== "全天") {
      const period = $(".vacationPeriod, .tbVacPeriod").first();
      period.prop("disabled", false);
      period.find("option").each(function () {
        if ($(this).text().trim() === values.period) {
          $(this).prop("selected", true);
        }
      });
      period.trigger("change");
    }

    $("textarea.DESCR200").val(values.reason).trigger("change");
    $("textarea.DESCR254").val(values.handover).trigger("change");
    $('textarea[name="ctl00$MainContentPortal$tbRPTCMMT"]')
      .val(values.advice)
      .trigger("change");
  }, input);

  const verification = await page.evaluate((values) => {
    const advice = document.querySelector('textarea[name*="tbRPTCMMT"]');
    const attachments = [...document.querySelectorAll("td")].map((cell) =>
      cell.textContent?.trim(),
    );
    return {
      adviceMatches: advice?.value === values.advice,
      attachmentVisible: attachments.includes(values.attachmentName),
      uploadPending: [...document.querySelectorAll(".layui-layer-content")].some(
        (layer) => layer.textContent?.includes("上传中"),
      ),
      fixedFlowSelected: Boolean(
        document.querySelector("#hdFixedFlow")?.value,
      ),
      begin: document.querySelector(".tbBeginDate")?.value,
      end: document.querySelector(".tbEndDate")?.value,
      leaveType: document.querySelector(".tbType")?.selectedOptions?.[0]?.text,
    };
  }, input);
  if (
    !verification.adviceMatches ||
    !verification.attachmentVisible ||
    verification.uploadPending ||
    !verification.fixedFlowSelected
  ) {
    throw new Error(`Form verification failed: ${JSON.stringify(verification)}`);
  }

  const screenshotPath = `/tmp/hna-leave-application/filled-${Date.now()}.png`;
  await page.screenshot({ path: screenshotPath });
  console.log(
    JSON.stringify({
      status: "filled_preview",
      taskSpaceId: task.spaceId,
      screenshotPath,
      verification,
      submitted: false,
    }),
  );
  await task.handOff();
}
