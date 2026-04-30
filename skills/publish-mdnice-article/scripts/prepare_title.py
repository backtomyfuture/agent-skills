#!/usr/bin/env python3
"""
Prepare a Markdown Nice title-fill script.

The generated JS fills the visible Ant Design "new article" modal title input
and clicks the primary confirmation button. This avoids shell quoting problems
when titles contain quotes, backticks, or other metacharacters.
"""

import argparse
from pathlib import Path


def escape_for_js(s: str) -> str:
    s = s.replace('\\', '\\\\')
    s = s.replace('`', '\\`')
    s = s.replace('${', '\\${')
    return s


def generate_js(title: str) -> str:
    escaped = escape_for_js(title)
    return f"""(() => {{
  const title = `{escaped}`;
  const inputSelector = 'body > div:nth-child(9) > div > div.ant-modal-wrap > div > div.ant-modal-content > div.ant-modal-body > div > div:nth-child(2) > div > span > input';
  const buttonSelector = 'body > div:nth-child(9) > div > div.ant-modal-wrap > div > div.ant-modal-content > div.ant-modal-footer > button.ant-btn.ant-btn-primary';

  const visible = el => !!el && el.offsetParent !== null;
  const modal = [...document.querySelectorAll('.ant-modal-content')]
    .find(el => visible(el) || el.getBoundingClientRect().width > 0);
  const input = [...(modal?.querySelectorAll('.ant-modal-body input') || [])]
      .find(el => el.placeholder === '请输入标题')
    || [...(modal?.querySelectorAll('.ant-modal-body input') || [])]
      .find(el => {{
        const labelText = el.closest('.ant-row, .ant-form-item, div')?.textContent || '';
        return labelText.includes('文章标题');
      }})
    || document.querySelector(inputSelector)
    || modal?.querySelector('.ant-modal-body input')
    || [...document.querySelectorAll('.ant-modal-body input')].find(visible);

  if (!input) return {{ ok: false, error: 'title input not found' }};

  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value');
  input.focus();
  if (descriptor?.set) descriptor.set.call(input, title);
  else input.value = title;
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));

  const button = document.querySelector(buttonSelector)
    || modal?.querySelector('.ant-modal-footer .ant-btn-primary')
    || [...document.querySelectorAll('.ant-modal-footer .ant-btn-primary, button.ant-btn-primary')]
      .find(visible);

  if (!button) return {{ ok: false, error: 'confirm button not found', titleFilled: true }};
  button.click();
  return {{ ok: true, title, clicked: true }};
}})()"""


def main():
    parser = argparse.ArgumentParser(description='Prepare Markdown Nice title-fill JS')
    parser.add_argument('title', help='Article title')
    parser.add_argument('--output', '-o', default='/tmp/mdnice_fill_title.js',
                        help='Output JS file path (default: /tmp/mdnice_fill_title.js)')
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_js(args.title), encoding='utf-8')
    print(str(output))


if __name__ == '__main__':
    main()
