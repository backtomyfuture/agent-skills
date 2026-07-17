#!/usr/bin/env python3
"""
Extract plain text from an Office report so you can rewrite it as newsletter
Markdown. Handles the two zip-based Office formats reliably without extra deps:

  - .pptx  → text per slide (slideN, in slide order)
  - .docx  → paragraphs in document order

For .pdf, this script is NOT the right tool — use the `pdf` skill or
`pdftotext file.pdf -` / the Read tool instead, which handle layout far better.

Usage:
    python3 extract_text.py /path/to/报告.pptx
    python3 extract_text.py /path/to/报告.docx

The output is meant for a human/LLM to read and restructure — it is deliberately
lightly formatted, not a faithful layout dump.
"""

import re
import sys
import zipfile


def _texts(xml):
    """All <a:t>/<w:t> run texts in document order, whitespace-trimmed.

    The `(?:\\s[^>]*)?` after `:t` matters: it requires the tag to be exactly
    `a:t`/`w:t` (optionally with attributes), so we don't accidentally match
    `<a:tbl>`, `<a:tableStyles>`, etc. and swallow raw XML between them.
    """
    runs = re.findall(r'<(?:a|w):t(?:\s[^>]*)?>(.*?)</(?:a|w):t>', xml, re.S)
    return [r for r in (t.strip() for t in runs) if r]


def extract_pptx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        slides = [n for n in z.namelist()
                  if re.match(r'ppt/slides/slide\d+\.xml$', n)]
        slides.sort(key=lambda n: int(re.findall(r'\d+', n)[0]))
        for n in slides:
            num = int(re.findall(r'\d+', n)[0])
            runs = _texts(z.read(n).decode('utf-8', 'ignore'))
            out.append(f"===== slide{num} =====")
            out.append(" | ".join(runs) if runs else "(no text)")
    return "\n".join(out)


def extract_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    # Split on paragraph boundaries so each <w:p> becomes one line.
    paras = re.split(r'</w:p>', xml)
    lines = []
    for p in paras:
        runs = _texts(p)
        if runs:
            lines.append("".join(runs))
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: extract_text.py <file.pptx|file.docx>")
    path = sys.argv[1]
    low = path.lower()
    if low.endswith('.pptx'):
        print(extract_pptx(path))
    elif low.endswith('.docx'):
        print(extract_docx(path))
    elif low.endswith('.pdf'):
        sys.exit("PDF detected — use the `pdf` skill or `pdftotext`/Read instead.")
    else:
        sys.exit(f"unsupported file type: {path}")


if __name__ == '__main__':
    main()
