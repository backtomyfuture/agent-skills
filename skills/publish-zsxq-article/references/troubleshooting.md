# Troubleshooting

Things that actually go wrong when running this skill, and how to recover.

## Table of contents

- [Browser and session problems](#browser-and-session-problems)
- [Login problems](#login-problems)
- [Content problems](#content-problems)
- [Image problems](#image-problems)
- [Save and publish problems](#save-and-publish-problems)
- [Shell quoting issues](#shell-quoting-issues)

---

## Browser and session problems

### "headed ignored: daemon already running"

A previous agent-browser process is still holding the session in headless mode, and you can't upgrade a headless daemon to headed in-place. Close everything and start fresh:

```bash
agent-browser close --all
```

Then re-run the Pre-flight steps. This is the single most common recoverable failure — always try it first.

### The page looks stale or doesn't respond to clicks

agent-browser has been known to hold onto a reference to an element that was re-rendered. Take a fresh snapshot before trusting any `@eN` ref:

```bash
agent-browser --session-name zsxq snapshot -i
```

If that still doesn't help, navigate back to the editor URL explicitly:

```bash
agent-browser --session-name zsxq open "https://wx.zsxq.com/article?groupId=88882188185282"
```

---

## Login problems

### Login redirect after opening the editor

The editor URL redirects to `/login` when the session is expired. In order of preference:

1. **Re-use the saved Chrome profile.** This is the most reliable path because it carries real Chrome cookies, localStorage, and service worker state.

   ```bash
   agent-browser --headed true --session-name zsxq --profile ~/.agent-browser/profiles/zsxq/ open "https://wx.zsxq.com/article?groupId=88882188185282"
   ```

2. **Fall back to `--auto-connect`.** This attaches to a Chrome instance you already have running and logged in.

   ```bash
   agent-browser close --all
   agent-browser --auto-connect open "https://wx.zsxq.com/article?groupId=88882188185282"
   ```

3. **Manual login flow.** Open the login page in headed mode, ask the user to log in by hand, then save the profile for next time.

   ```bash
   agent-browser --headed true --session-name zsxq open "https://wx.zsxq.com/login"
   # user logs in manually, confirms back
   mkdir -p ~/.agent-browser/profiles/zsxq
   agent-browser --session-name zsxq state save ~/.agent-browser/states/zsxq-auth.json
   ```

### Why `--profile` beats `--state`

The exported state JSON often looks fine on disk but silently fails to restore cookies with `HttpOnly` or `SameSite=None` attributes. A persistent Chrome profile directory sidesteps the serialization round-trip entirely. If you have both, prefer the profile.

---

## Content problems

### Markdown shows up as raw text in the editor

The content was inserted via `fill` or `type` instead of a synthetic paste event. Milkdown only parses Markdown when it intercepts a paste with `text/plain`. Re-run the content paste step using the generated JS file:

```bash
agent-browser --session-name zsxq eval "$(cat /tmp/zsxq_paste_content.js)"
```

### Content too long

Zsxq enforces a 100,000-character limit. `prepare_content.py` emits a warning on stderr when the body exceeds this. The skill has no way to split an article for you — ask the user whether to truncate or to split into multiple posts, then re-run.

### Notion metadata still appears in the content

`prepare_content.py` strips a known set of keys (see `NOTION_META_KEYS` in the script). If your Notion export has a key the script doesn't know about (e.g. `Updated:`, `Project:`), either:

1. Clean the generated `/tmp/zsxq_paste_content.js` by hand before eval, or
2. Add the missing key to `NOTION_META_KEYS` in `scripts/prepare_content.py` — this is the more durable fix.

### The input path is a directory, not a file

This is expected for Notion exports. `prepare_content.py` handles it: it auto-selects the sole `.md` file, or prints a list of choices if there are multiple. If it prints a list, pass the exact file path on the next call.

### JS SyntaxError inside `agent-browser eval`

Constructing JS inline in shell makes backticks, `$`, and quotes nearly impossible to get right across all inputs. Always go through `prepare_content.py` or `prepare_image.py` to produce a `.js` file, then `eval "$(cat /tmp/...)"`.

---

## Image problems

### Image count looks wrong after paste

ProseMirror inserts invisible "separator" nodes that also contain `<img>` elements. Count only the real ones:

```javascript
document.querySelectorAll('.ProseMirror img:not(.ProseMirror-separator)[src]').length
```

### Image inserted at the wrong position

Almost always caused by merging the marker-deletion and image-paste into one eval. ProseMirror needs a moment (roughly 500ms in practice) to sync its internal selection state with the DOM after a mutation. Keep the three-step sequence in the image pipeline separated by the explicit `agent-browser wait 500`.

### Images in a nested subdirectory (Notion exports)

Notion often emits `Article Name/image 1.png` inside the folder it gives you. `prepare_content.py` resolves paths relative to the `.md` file's directory, so this usually works. If `resolved_path` is `null` in the JSON summary, list the actual directory contents with Python (`os.listdir`) to find the image and pass that absolute path to `prepare_image.py` directly.

### Fallback to system clipboard?

This used to be a supported path. It has been removed. Synthetic `ClipboardEvent` via `prepare_image.py` has been reliable enough that keeping the clipboard fallback only added confusion and a macOS-only dependency.

---

## Save and publish problems

### "Save" button gives no visible feedback

Expected. Zsxq does not show a toast when a draft is saved. Verify by clicking "我的文章" in the sidebar and confirming the article appears under "草稿箱".

### Scheduled-publish button still shows "发布"

If the publish button text didn't change to "定时发布" after setting the date and time, one of two things failed:

1. The schedule switch (`.scheduled-topic-timer label.green`) was not toggled on. Click it and re-run the time setter.
2. flatpickr did not accept the date. Check `input._flatpickr` is truthy in the eval result.

Do not click the button while it still says "发布" — that publishes instantly, which we never want.

---

## Shell quoting issues

### Paths with `&`, `|`, `;`, `$`, or spaces

Always single-quote the path. Single quotes disable every shell expansion except for literal `'`, which is rare in filenames:

```bash
python3 /Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_content.py '/Users/jarod/Downloads/Private & Shared/Article.md'
```

If the tooling rejects the command outright (some runners refuse arguments containing `&` even when quoted), use Python subprocess with a list of arguments, which bypasses the shell entirely:

```python
import subprocess
subprocess.run([
    "python3",
    "/Users/jarod/.agents/skills/publish-zsxq-article/scripts/prepare_content.py",
    "/path/with &/special chars.md",
], capture_output=True, text=True)
```
