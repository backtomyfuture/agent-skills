#!/usr/bin/env python3
"""Stage a prepared Toutiao payload with agent-browser only.

This helper does not use Selenium. It wraps the same browser session workflow
used in the skill, but makes ProseMirror title/body staging deterministic by
using agent-browser eval against the live Toutiao editor.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"


def run_agent_browser(session: str, args: list[str], stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["agent-browser", "--session-name", session, *args]
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed:\n{result.stdout}")
    return result


def load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body_file = Path(payload["body_file"]).expanduser()
    if not body_file.exists():
        raise SystemExit(f"body_file not found: {body_file}")
    for image in payload.get("images", []):
        resolved = image.get("resolved_path")
        if resolved and not Path(resolved).exists():
            raise SystemExit(f"image missing: {resolved}")
    return payload


def text_to_html(text: str) -> str:
    blocks: list[str] = []
    for line in text.rstrip().splitlines():
        stripped = line.strip()
        if stripped:
            blocks.append(f"<p>{html.escape(stripped)}</p>")
        else:
            blocks.append("<p><br></p>")
    return "".join(blocks) or "<p><br></p>"


def b64_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def stage_title_and_body(session: str, title: str, body_html: str) -> dict[str, Any]:
    script = f"""
(() => {{
  const decode = b64 => new TextDecoder('utf-8').decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
  const title = decode('{b64_text(title)}');
  const bodyHtml = decode('{b64_text(body_html)}');

  const titleEl = document.querySelector("textarea[placeholder*='请输入文章标题'], input[placeholder*='请输入文章标题']");
  if (!titleEl) throw new Error('title input not found');
  titleEl.focus();
  titleEl.value = title;
  titleEl.dispatchEvent(new Event('input', {{bubbles: true}}));
  titleEl.dispatchEvent(new Event('change', {{bubbles: true}}));

  const host = document.querySelector('.syl-editor');
  if (!host) throw new Error('syl-editor host not found');
  const key = Reflect.ownKeys(host).map(String).find(k => k.startsWith('__reactInternalInstance'));
  if (!key) throw new Error('React fiber key not found on syl-editor');
  const editor = host[key].return && host[key].return.stateNode && host[key].return.stateNode.editor;
  if (!editor) throw new Error('Toutiao editor instance not found');
  editor.setHTML(bodyHtml);

  const text = editor.getText();
  const html = editor.getHTML();
  return {{
    title: titleEl.value,
    textLen: text.length,
    textStart: text.slice(0, 90),
    textEnd: text.slice(-160),
    htmlStart: html.slice(0, 140),
    markers: {{
      img1: (text.match(/\\[\\[IMG_1\\]\\]/g) || []).length,
      img2: (text.match(/\\[\\[IMG_2\\]\\]/g) || []).length,
      img3: (text.match(/\\[\\[IMG_3\\]\\]/g) || []).length
    }},
    imageTags: (html.match(/<img\\b/g) || []).length,
    hasEnding: text.includes('参考来源') || text.includes('参考资料')
  }};
}})()
"""
    result = run_agent_browser(session, ["eval", "--stdin"], stdin=script)
    return json.loads(result.stdout)


def editor_stats(session: str) -> dict[str, Any]:
    script = """
(() => {
  const host = document.querySelector('.syl-editor');
  const key = host && Reflect.ownKeys(host).map(String).find(k => k.startsWith('__reactInternalInstance'));
  const editor = key && host[key].return && host[key].return.stateNode && host[key].return.stateNode.editor;
  if (!editor) throw new Error('Toutiao editor instance not found');
  const text = editor.getText();
  const html = editor.getHTML();
  return {
    textLen: text.length,
    markers: {
      img1: (text.match(/\\[\\[IMG_1\\]\\]/g) || []).length,
      img2: (text.match(/\\[\\[IMG_2\\]\\]/g) || []).length,
      img3: (text.match(/\\[\\[IMG_3\\]\\]/g) || []).length
    },
    imageTags: (html.match(/<img\\b/g) || []).length,
    hasEnding: text.includes('参考来源') || text.includes('参考资料')
  };
})()
"""
    result = run_agent_browser(session, ["eval", "--stdin"], stdin=script)
    return json.loads(result.stdout)


def select_marker(session: str, marker: str) -> dict[str, Any]:
    script = f"""
(() => {{
  const marker = '{marker}';
  const host = document.querySelector('.syl-editor');
  const key = host && Reflect.ownKeys(host).map(String).find(k => k.startsWith('__reactInternalInstance'));
  const editor = key && host[key].return && host[key].return.stateNode && host[key].return.stateNode.editor;
  if (!editor) throw new Error('Toutiao editor instance not found');
  const view = editor.view;
  let found = null;
  view.state.doc.descendants((node, pos) => {{
    if (found) return false;
    if (node.isText && node.text && node.text.includes(marker)) {{
      const idx = node.text.indexOf(marker);
      found = {{from: pos + idx, to: pos + idx + marker.length}};
      return false;
    }}
    return true;
  }});
  if (!found) return {{ok: false, marker}};
  const Sel = view.state.selection.constructor;
  view.dispatch(view.state.tr.setSelection(Sel.create(view.state.doc, found.from, found.to)).scrollIntoView());
  view.focus();
  return {{ok: true, marker, selectedText: view.state.doc.textBetween(found.from, found.to)}};
}})()
"""
    result = run_agent_browser(session, ["eval", "--stdin"], stdin=script)
    return json.loads(result.stdout)


def try_upload_image(session: str, image: dict[str, Any]) -> str:
    marker = image.get("marker")
    resolved = image.get("resolved_path")
    if not marker or not resolved:
        return "missing marker/path"
    selected = select_marker(session, marker)
    if not selected.get("ok"):
        return f"{marker}: marker not found"
    before = editor_stats(session)
    run_agent_browser(session, ["click", ".syl-toolbar-tool.image button"])
    selectors = [
        "input[type=file][accept*=image]",
        "input[type=file]",
    ]
    upload_output = ""
    for selector in selectors:
        attempt = run_agent_browser(session, ["upload", selector, str(Path(resolved).resolve())], check=False)
        upload_output += attempt.stdout
        if attempt.returncode == 0:
            break
    run_agent_browser(session, ["find", "text", "确定", "click", "--exact"], check=False)
    time.sleep(3)
    after = editor_stats(session)
    if after.get("imageTags", 0) > before.get("imageTags", 0):
        return f"{marker}: uploaded"
    return f"{marker}: upload not confirmed; agent-browser output={upload_output.strip()[:160]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage a Toutiao payload with agent-browser only.")
    parser.add_argument("payload", help="Path to payload.json")
    parser.add_argument("--session-name", default="toutiao")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--open", action="store_true", help="Open the Toutiao article editor before staging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = load_payload(Path(args.payload).expanduser().resolve())
    body = Path(payload["body_file"]).read_text(encoding="utf-8")
    body_html = text_to_html(body)
    if args.open:
        run_agent_browser(args.session_name, ["open", PUBLISH_URL])
    staged = stage_title_and_body(args.session_name, payload["title"], body_html)
    image_results: list[str] = []
    if not args.skip_images:
        for image in payload.get("images", []):
            image_results.append(try_upload_image(args.session_name, image))
    result = {
        "status": "staged_autosaved",
        "title": payload["title"],
        "staged": staged,
        "image_results": image_results,
        "final_publish_clicked": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
