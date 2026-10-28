import { fileURLToPath } from "node:url";

const INDEX_URL = "http://oa3.hnair.net/oawebapp/index.aspx";

async function waitForQueryLink(page, timeout = 12000) {
  return page
    .waitForFunction(
      () =>
        [...document.querySelectorAll("a")].some(
          (link) => link.textContent?.trim() === "公文查询"
        ),
      undefined,
      { timeout }
    )
    .then(() => true)
    .catch(() => false);
}

export async function queryOALeaveDocuments(targetYear = new Date().getFullYear()) {
  const yearStr = String(targetYear);
  const task = await taskSpace(`kaoqin-query-oa-${Date.now()}`);
  const page = task.page("p1");

  try {
    await page.goto(INDEX_URL);

    const hasQueryLink = await waitForQueryLink(page);
    if (!hasQueryLink) {
      return {
        success: false,
        error: "login_required",
        message: "未能进入海航OA公文系统，请先在浏览器中登录OA系统",
        url: await page.url(),
      };
    }

    // 点击公文查询菜单
    await page.evaluate(() => {
      const link = [...document.querySelectorAll("a")].find(
        (item) => item.textContent?.trim() === "公文查询"
      );
      if (link) link.click();
    });

    // 等待查询表单 iframe 出现
    await page.waitForFunction(
      () =>
        Boolean(
          document
            .querySelector("iframe")
            ?.contentDocument?.querySelector("#ibtQuerySubmit")
        ),
      undefined,
      { timeout: 15000 }
    );

    // 填写年份与“我呈报的公文”并提交查询
    await page.evaluate((yr) => {
      const doc = document.querySelector("iframe").contentDocument;
      const selYear = doc.querySelector("#SelDate1_SelYear");
      if (selYear) selYear.value = yr;

      const ddlDirection = doc.querySelector("#ddlDocDirection");
      if (ddlDirection) ddlDirection.value = "0701"; // 我呈报的公文

      const selMonth = doc.querySelector("#SelDate1_SelMonth");
      if (selMonth) selMonth.value = "1";
      const selDay = doc.querySelector("#SelDate1_SelDay");
      if (selDay) selDay.value = "1";
      const selEndMonth = doc.querySelector("#SelDate1_SelEndMonth");
      if (selEndMonth) selEndMonth.value = "12";
      const selEndDay = doc.querySelector("#SelDate1_SelEndDay");
      if (selEndDay) selEndDay.value = "31";

      const submitBtn = doc.querySelector("#ibtQuerySubmit");
      if (submitBtn) submitBtn.click();
    }, yearStr);

    // 等待结果表格呈现
    await page.waitForFunction(
      () =>
        Boolean(
          document
            .querySelector("iframe")
            ?.contentDocument?.querySelector("#tgDocQuery")
        ),
      undefined,
      { timeout: 20000 }
    );

    // 提取休假公文列表并在浏览器上下文内并行抓取请示内容
    const docs = await page.evaluate(async (yr) => {
      const doc = document.querySelector("iframe").contentDocument;
      const table = doc.querySelector("#tgDocQuery");
      if (!table) return [];

      const rows = table.querySelectorAll("tr");
      const leaveDocs = [];

      for (let i = 1; i < rows.length; i++) {
        const cells = rows[i].querySelectorAll("td");
        if (cells.length < 9) continue;

        const titleLink = cells[3].querySelector("a");
        const titleText = cells[3].innerText.trim();
        const docType = cells[2].innerText.trim();
        const secLevel = cells[4].innerText.trim();
        const submitTime = cells[5].innerText.trim();
        const reporter = cells[8].innerText.trim();

        const isLeave =
          docType === "HRM休假申请" ||
          titleText.includes("休假") ||
          titleText.includes("补休") ||
          titleText.includes("年假") ||
          titleText.includes("倒休");

        if (!isLeave) continue;

        let commonPartId = "";
        let fileType = "3112";
        if (titleLink && titleLink.href) {
          const idMatch = titleLink.href.match(/cniCommonPartId=([^&]+)/);
          if (idMatch) commonPartId = idMatch[1];
          const ftMatch = titleLink.href.match(/cnvcFileType=([^&]+)/);
          if (ftMatch) fileType = ftMatch[1];
        }

        if (commonPartId) {
          leaveDocs.push({
            rank: i,
            type: docType,
            title: titleText,
            security: secLevel,
            submit_time: submitTime,
            reporter: reporter,
            part_id: commonPartId,
            file_type: fileType,
            request_content: "",
          });
        }
      }

      // 并行请求公文详情并解码 GBK
      const decoder = new TextDecoder("gbk");
      await Promise.all(
        leaveDocs.map(async (item) => {
          try {
            const viewUrl = `http://oa3.hnair.net/OAWebApp/OA/Document/Query/QueryToView.aspx?cniCommonPartId=${item.part_id}&cnvcFileType=${item.file_type}&strSubUser=&strDBYear=${yr}&strAllotId=&strSecTypeId=0201&strNoteId=`;
            const resp = await fetch(viewUrl);
            const buf = await resp.arrayBuffer();
            const html = decoder.decode(buf);
            const match = html.match(
              /id="UcViewAdv1_lbContent"[^>]*>([\s\S]*?)<\/span>/i
            );
            if (match) {
              item.request_content = match[1]
                .replace(/<br\s*\/?>/gi, "\n")
                .replace(/&nbsp;/g, " ")
                .replace(/<[^>]+>/g, "")
                .trim();
            }
          } catch (e) {
            item.request_content = "";
          }
        })
      );

      return leaveDocs;
    }, yearStr);

    return {
      success: true,
      year: targetYear,
      docs,
    };
  } finally {
    try {
      await task.finish({ keep: [] });
    } catch (_) {}
  }
}

// 支持作为 CLI 脚本直接运行
const isMain =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === process.argv[1];

if (isMain) {
  const yearArg = process.env.QUERY_YEAR
    ? parseInt(process.env.QUERY_YEAR, 10)
    : (process.argv[2] ? parseInt(process.argv[2], 10) : new Date().getFullYear());
  const res = await queryOALeaveDocuments(yearArg);
  console.log(JSON.stringify(res, null, 2));
}
