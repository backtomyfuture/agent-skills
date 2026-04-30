# Editor Internals

Everything you need to know about how the Zsxq article editor is built, and why the skill treats it the way it does. Read this when a selector fails, the editor behaves unexpectedly, or you're trying to extend the skill to a new interaction.

## Two editor modes

Zsxq's article editor has two underlying implementations, toggled by a button in the toolbar:

- **Rich text mode (Quill).** The default. Pasting Markdown here inserts it as literal text — hash signs, asterisks, everything. Useless for our purposes.
- **Markdown mode (Milkdown, built on ProseMirror).** A WYSIWYG editor that parses Markdown when it arrives via a paste event and renders the result as rich content. This is the mode the skill targets.

The skill switches to Markdown mode before doing anything else. You can detect which mode you're in by checking for the editor root element:

- `.ProseMirror` present → Milkdown / Markdown mode
- `.ql-editor` present → Quill / rich text mode

## How Milkdown intercepts paste events

Milkdown attaches a `paste` handler to the ProseMirror root. It inspects `clipboardData` and dispatches based on the payload type:

- **Text paste with `text/plain` that looks like Markdown** → parsed by a Markdown-to-ProseMirror-doc transformer, inserted as a rich node tree.
- **Binary paste containing image `File` objects** → uploaded to Zsxq's CDN, and once the upload resolves, inserted as an `<img>` node at the cursor.

This is the entire basis for the skill's injection strategy: we never type anything; we construct a synthetic `ClipboardEvent` with exactly the right payload and dispatch it on the editor root. That's what `prepare_content.py` and `prepare_image.py` generate JS for.

## Why image insertion has to be three separate eval calls

ProseMirror's state (`EditorState`) is an immutable data structure separate from the DOM. Deleting a range through a ProseMirror transaction (`view.dispatch(tr.delete(...))`) updates state synchronously, but the corresponding DOM mutation and selection sync happen on a subsequent microtask tick. If we paste the image immediately after the delete in the same JS execution, the paste handler runs against a cursor position that's still pointing at the pre-delete coordinates, and the image lands in the wrong place.

The fix is to let ProseMirror catch up between operations: delete the marker, `wait 500`, then paste the image. 500ms is empirical — it has been reliable across many runs.

## Element reference

| Element | Selector | Notes |
|---------|----------|-------|
| Title input | `input[placeholder=请在这里输入标题]` | Hard limit 60 chars |
| Content editor (Markdown mode) | `.ProseMirror` | Milkdown's ProseMirror root |
| Content editor (rich text mode) | `.ql-editor` | Quill — we switch away from this |
| Mode switch button | `.toggle-mode` | JS click; toggles Rich Text ↔ Markdown |
| Mode switch confirm dialog | `.confirm` | JS click to accept the switch |
| Restore-draft popup dismiss | `button/.cancel/.btn` with exact text `忽略` | Match exact text; many buttons share these classes |
| Save draft button | Element with text `保存` | `find text` works reliably here |
| "My articles" sidebar entry | Element with text `我的文章` | Navigates to draft list |
| Drafts section header | `草稿箱` | Where saved drafts appear |
| Real (visible) image nodes | `.ProseMirror img:not(.ProseMirror-separator)[src]` | Excludes invisible ProseMirror helper nodes |
| Schedule enable switch | `.scheduled-topic-timer label.green` | Toggle on to reveal time pickers |
| Schedule date input | `.scheduled-topic-timer #date.flatpickr-input` | Readonly; mutate via `input._flatpickr.setDate(...)` |
| Schedule hour / minute lists | `.scheduled-topic-timer app-topic-timer .time` | Two boxes, each with `li` children |
| Publish button | `.operation-btns .post.btn` | Text is `发布` normally, becomes `定时发布` when schedule is on |

## Programmatic access to ProseMirror state

The ProseMirror `EditorView` instance is reachable from the DOM root as `editor.pmViewDesc.view`. This is what lets us run position-accurate transactions for marker deletion:

```javascript
const editor = document.querySelector('.ProseMirror');
const view = editor?.pmViewDesc?.view;
view.state.doc.descendants((node, pos) => { /* walk nodes */ });
view.dispatch(view.state.tr.delete(from, to));
```

If `pmViewDesc.view` is ever not there (editor not fully initialized, or Milkdown upgrades to a different internal API), the marker-deletion code falls back to a `TreeWalker` that mutates the DOM directly. ProseMirror re-reads the DOM on its next mutation, so this still works, just less elegantly.

## Known gotchas in the Quill-to-Milkdown switch

After toggling from Quill to Milkdown, Zsxq sometimes shows a "恢复上次编辑的内容" (restore previous content) dialog. The dismiss button is labeled `忽略` (Ignore). The restore button reuses the same `.confirm` class as the mode-switch confirm, so a generic `.confirm` click here would wipe your fresh content. The skill matches the exact text `忽略` to avoid this.
