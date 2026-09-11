---
name: publish-mdnice-article
description: >-
  Stage a Markdown or Notion-sourced article in Markdown Nice
  (editor.mdnice.com). Use this skill whenever the user mentions Markdown Nice,
  mdnice, editor.mdnice.com, 发布到 markdown nice, 发布到 mdnice, or asks to
  turn a Notion page or Markdown file into a Markdown Nice draft. The workflow
  creates an article, fills its title, inserts Markdown and images, verifies
  the editor, and leaves the autosaved page open without publishing.
---

# Stage a Markdown Nice article

Use Ego Lite to create and fill a new article at `https://editor.mdnice.com/`.
Markdown Nice autosaves the draft. The workflow ends with the filled page handed
off to the user; it never publishes the article.

## Inputs and invariants

- Primary editor: `#nice-md-editor`.
- Use exactly one Ego Lite TaskSpace for the whole run.
- Create a TaskSpace on the first round. On a login round, return its numeric
  `taskSpaceId`; after the user logs in, reclaim that same TaskSpace.
- The stage helper reports `login_required` before editing when the editor is
  not ready, and calls `task.handOff()` so the user can complete login.
- Create the article before pasting Markdown. Process image markers in order.
  For every image, delete its marker, wait briefly, then paste the image in a
  separate `page.evaluate()` call.
- Verify CodeMirror (or the editor fallback) has nonzero content and no
  `[[IMG_N]]` markers. Save a screenshot under `/tmp/mdnice-article`.
- Every successful stage reports `submitted: false` and hands off the filled
  page. There is no publish or manual-save step.

## Helper scripts

All paths below are absolute for this checkout:

- `scripts/notion_ingest.py` localizes remote Notion images and rewrites image
  references to local files. Its output can be passed to `prepare_content.py`.
- `scripts/prepare_content.py` extracts the first H1 title, removes export
  metadata, replaces image references with `[[IMG_N]]`, and writes a generated
  JavaScript string for Ego Lite `page.evaluate()`.
- `scripts/prepare_title.py` writes a generated JavaScript string that fills
  the visible new-article title input and confirms the modal.
- `scripts/prepare_image.py` writes a generated JavaScript string that pastes
  one binary image through a synthetic clipboard event. Marker deletion stays
  separate because editor re-rendering can otherwise move the insertion point.
- `scripts/stage.mjs` owns the browser workflow. It loads each generated JS
  file in Node.js and passes the source string to `page.evaluate()`.

The Python helpers preserve their existing output JSON. A content summary has
`title`, `js_file`, and `images`; each image entry can be paired with the
`js_file` emitted by `prepare_image.py` as `{ marker, jsPath }` for staging.

## Prepare content

For a local Markdown file:

```bash
python3 /Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/prepare_content.py \
  '/absolute/path/article.md' \
  --output /tmp/mdnice-article/content.js
```

Use the JSON summary as the source of truth. Keep its `title` and `images`
values. For each image with a non-null `resolved_path`, generate a separate
paste script:

```bash
mkdir -p /tmp/mdnice-article
python3 /Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/prepare_image.py \
  '/absolute/path/image.png' \
  --output /tmp/mdnice-article/image-1.js
```

If an image has `resolved_path: null`, report the missing file and ask whether
to continue without that image; do not infer a path.

If the source is a Notion URL, obtain its author-written Markdown with the
available Notion integration, then localize its images before preparing it:

```bash
mkdir -p /tmp/mdnice-notion
python3 /Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/notion_ingest.py \
  --input /tmp/mdnice-notion/raw.md \
  --output-dir /tmp/mdnice-notion
python3 /Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/prepare_content.py \
  /tmp/mdnice-notion/article.md \
  --output /tmp/mdnice-article/content.js
```

Do not modify the original Markdown file or the Notion page. Temporary
transforms belong under `/tmp`.

## Start or resume the Ego Lite stage

Run the importable helper inside `ego-browser nodejs`. Supply the title,
generated content JS path, and one generated image JS path per marker. The
helper accepts `jsPath` or `jsFile` for image scripts.

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/stage.mjs";

await stage({
  title: "Article title from the content summary",
  contentJsPath: "/tmp/mdnice-article/content.js",
  images: [
    { marker: "[[IMG_1]]", jsPath: "/tmp/mdnice-article/image-1.js" },
    { marker: "[[IMG_2]]", jsPath: "/tmp/mdnice-article/image-2.js" },
  ],
});
EOF
```

The helper creates one TaskSpace, opens Markdown Nice, waits for the editor,
opens **新建文章**, fills the title, evaluates the generated body script, then
handles each image marker with the required delete/wait/paste sequence. It
writes a screenshot and prints JSON similar to:

```json
{
  "status": "filled_preview",
  "taskSpaceId": 123,
  "screenshotPath": "/tmp/mdnice-article/filled-1700000000000.png",
  "verification": { "length": 5432, "markerCount": 0, "method": "codemirror" },
  "submitted": false
}
```

If the first call prints `status: "login_required"`, it has already handed
control to the user. Ask the user to log in in the handed-off Ego Lite page.
After confirmation, run the same inputs with the returned `taskSpaceId`:

```bash
ego-browser nodejs <<'EOF'
import { stage } from "/Users/jarod/Documents/agent-skills/skills/publish-mdnice-article/scripts/stage.mjs";

await stage({
  taskSpaceId: 123,
  title: "Article title from the content summary",
  contentJsPath: "/tmp/mdnice-article/content.js",
  images: [
    { marker: "[[IMG_1]]", jsPath: "/tmp/mdnice-article/image-1.js" },
    { marker: "[[IMG_2]]", jsPath: "/tmp/mdnice-article/image-2.js" },
  ],
});
EOF
```

The continuation must use the same `taskSpaceId`; do not create a second
TaskSpace to recover from login or an unexpected page. If the editor still is
not ready after the continuation, stop and ask the user to inspect the handed
page rather than routing around the existing TaskSpace.

## Windows notes

The Python helpers read Markdown as `utf-8-sig` and write UTF-8 generated JS,
so a BOM does not leak into the title or body. `prepare_content.py` normalizes
local links such as `![](<./media/image.png>)` before resolving them.
`prepare_image.py` compresses oversized images through Pillow, or through its
Windows image fallback when available, before generating the inline payload.
Lower `--max-size` if a generated image script is too large. These scripts are
loaded from files by `stage.mjs`, so no generated JavaScript is passed as a
shell argument.

## Completion

Report the article title, the screenshot path, the returned `taskSpaceId`, and
that Markdown Nice autosaved the filled draft. State clearly that nothing was
published. Leave the handed-off editor open for the user to review.
