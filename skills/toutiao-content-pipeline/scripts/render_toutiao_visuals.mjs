import fs from "node:fs";
import path from "node:path";

function required(value, name) {
  if (!value || !String(value).trim()) throw new Error(`${name} is required`);
  return String(value);
}

export async function render({ planPath, taskSpaceId }) {
  const planFile = path.resolve(required(planPath, "planPath"));
  const plan = JSON.parse(fs.readFileSync(planFile, "utf8"));
  const task = taskSpaceId
    ? await takeOverTaskSpace(taskSpaceId)
    : await taskSpace("Toutiao local visual rendering");
  const page = task.page("p1");
  const rendered = [];
  for (const visual of plan.visuals ?? []) {
    const url = visual.open_url || new URL(`file://${visual.html_file}`).href;
    await page.goto(url);
    await page.waitForFunction(
      () => Boolean(document.querySelector("#card")),
      undefined,
      { timeout: 10_000 },
    );
    const clip = await page.evaluate(() => {
      const rect = document.querySelector("#card")?.getBoundingClientRect();
      if (!rect) throw new Error("Visual card not found");
      return {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      };
    });
    await page.screenshot({ path: path.resolve(visual.png_file), clip });
    if (!fs.existsSync(visual.png_file) || fs.statSync(visual.png_file).size === 0) {
      throw new Error(`Visual screenshot was not created: ${visual.png_file}`);
    }
    rendered.push({ id: visual.id, png_file: visual.png_file, status: "rendered" });
  }
  const result = {
    status: "visuals_rendered",
    taskSpaceId: task.spaceId,
    rendered,
    authenticated_publishing: false,
  };
  console.log(JSON.stringify(result, null, 2));
  await task.finish({ keep: [] });
  return result;
}
