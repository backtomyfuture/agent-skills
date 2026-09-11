---
name: youdao-export
description: >
  Export all files from Youdao Cloud Notes (有道云笔记) to local filesystem,
  preserving original folder structure. Supports notes exported as .docx,
  Word attachments, PDF, Excel, and PPT, with post-download verification.
  Use when the user wants to export, back up, or download from Youdao Cloud
  Notes. The workflow uses one Ego Lite TaskSpace, hands off only for manual
  login, and resumes the same task after the user returns control.
---

# 有道云笔记全量导出

Use Ego Lite to export the files in `https://note.youdao.com/web` to a local
directory while preserving the visible folder tree. Notes use **导出为Word**;
other supported attachments use **下载**. The workflow verifies the local
result before it closes the TaskSpace.

## Safety and inputs

- Use exactly one Ego Lite TaskSpace for the entire export and verification.
- The default output directory is `~/Downloads/youdao-export`; accept an
  explicit absolute path when the user provides one.
- A missing or expired login is normal. Open the site, report
  `login_required`, call `task.handOff()`, and ask the user to log in in the
  handed-off Ego Lite page. Resume with the returned `taskSpaceId`; do not
  create a second TaskSpace.
- Use only the managed Ego Lite session; never read, copy, or persist browser
  credentials or session state.
- Treat an ambiguous download as failed. Do not click the same menu item again
  without inspecting the current page.

## Export and verify

Prepare the output directory and run the importable helper in Ego Lite:

```bash
ego-browser nodejs <<'EOF'
import { exportAll } from "/Users/jarod/Documents/agent-skills/skills/youdao-export/scripts/export-all.mjs";

await exportAll({
  outputDir: "/Users/you/Downloads/youdao-export",
});
EOF
```

The helper:

1. creates or reclaims the single TaskSpace and opens the Youdao page;
2. hands off for manual login when the folder tree is unavailable;
3. rebuilds the virtual folder tree before each folder click;
4. excludes child folders from the file list;
5. opens each file, reveals the toolbar, and clicks the appropriate visible
   action;
6. arms `page.waitForEvent("download")` before the action and saves the
   completed artifact with `download.saveAs()` into the target folder;
7. skips files already present using the existing prefix matching rules;
8. verifies missing, extra, and extra-folder results through
   `scripts/verify.mjs`;
9. prints a structured report and a local screenshot, then closes the
   TaskSpace.

If the first call reports `login_required`, reuse the same inputs and ID:

```bash
ego-browser nodejs <<'EOF'
import { exportAll } from "/Users/jarod/Documents/agent-skills/skills/youdao-export/scripts/export-all.mjs";

await exportAll({
  taskSpaceId: 123,
  outputDir: "/Users/you/Downloads/youdao-export",
});
EOF
```

Do not call `task.finish()` after `login_required`; the helper has already
handed the page to the user. The continuation owns the same task and finishes
it only after export and verification succeed.

## Standalone verification round

If export and verification must be separated, reclaim the same TaskSpace and
call the verifier with its managed page:

```bash
ego-browser nodejs <<'EOF'
import { verifyExport } from "/Users/jarod/Documents/agent-skills/skills/youdao-export/scripts/verify.mjs";

const task = await taskSpace(123);
const page = task.page("p1");
console.log(await verifyExport({
  page,
  outputDir: "/Users/you/Downloads/youdao-export",
}));
EOF
```

Use the actual `taskSpaceId` returned by the export round. Keep the page open
only if the user needs to inspect it; otherwise finish the TaskSpace after the
verification result is recorded.

## Results

Report:

- output directory;
- total web files, newly downloaded files, skipped existing files, and failed
  downloads;
- renamed duplicate suffixes;
- verification totals;
- missing files, extra files, or extra folders;
- screenshot path and whether verification succeeded.

Do not claim a complete export when `verification.success` is false.
