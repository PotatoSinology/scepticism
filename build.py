#!/usr/bin/env python3
"""Build index.html from the article markdown.

    python3 build.py

Requires pandoc. Slides ("waypoints") are marked in the article with

    <!-- slide 3: some label -->
    ...block quotes, images, tables...
    <!-- /slide -->

and announced in the script with lines containing "▶ DIAPO 3".
"""
import html
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ARTICLE = ROOT / "draft_article_FINAL.md"
SCRIPT = ROOT / "draft_script_FINAL.md"
OUT = ROOT / "index.html"
IMG_DIR = "illustrations"

# Shown at the top of the page; leave empty to omit.
TITLE = "Penser avec l’anachronisme : « science » et frontières des savoirs en Chine ancienne"
AUTHOR = "Daniel Patrick MORGAN (CNRS-CRCAO)"
EVENT = ("« Peut-on ou doit-on parler de science mésopotamienne ? "
         "Différents points de vue sur une définition », 17 novembre 2026")

# CJK ideographs (incl. extensions) and the punctuation found inside Chinese runs.
HAN = r"⺀-⿟㐀-䶿一-鿿豈-﫿\U00020000-\U0003ffff"
ZH_PUNCT = r"　-〿＀-￯⋯"
ZH_RUN = re.compile(rf"[ \u00a0]?[{HAN}「『（〔《][{HAN}{ZH_PUNCT}]*")
LATIN = re.compile(r"[A-Za-zÀ-ÿ]")


def preprocess(md: str):
    """Markdown tweaks before pandoc. Returns (markdown, [slide labels])."""
    labels = []

    def open_slide(m):
        n = len(labels) + 1
        if m.group(1) and int(m.group(1)) != n:
            print(f"warning: marker says slide {m.group(1)} but it is slide {n} in order")
        label = (m.group(2) or "").strip()
        labels.append(label)
        return (f'<div class="slide" id="slide-{n}" data-n="{n}" '
                f'data-label="{html.escape(label, quote=True)}">')

    md = re.sub(r"<!--\s*slide\s*(\d+)?\s*:?\s*(.*?)\s*-->", open_slide, md)
    md, closes = re.subn(r"<!--\s*/slide\s*-->", "</div>", md)
    if closes != len(labels):
        sys.exit(f"error: {len(labels)} slide markers but {closes} '<!-- /slide -->'")

    out = []
    for line in md.split("\n"):
        prev = out[-1] if out else ""
        # Speaking times in headings, e.g. "# Catégories (6:00)"
        if line.startswith("#"):
            line = re.sub(r"\s*\(\d+:\d\d\)\s*$", "", line)
        # Obsidian embeds: ![[file.svg|alt]]
        line = re.sub(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]",
                      lambda m: f"![]({IMG_DIR}/{m.group(1)})", line)
        # In block quotes, every source line becomes its own paragraph, so that
        # a Chinese line and its translation can be styled/hidden separately.
        if (line.startswith(">") and line[1:].strip()
                and prev.startswith(">") and prev[1:].strip()):
            out.append(">")
        # Captions directly under a table or image need a blank line.
        if re.match(r"\*\*(Figure|Tableau)\b", line) and prev.strip():
            out.append("")
        out.append(line)
    return "\n".join(out), labels


def pandoc(md: str) -> str:
    fmt = "markdown-smart-implicit_figures"
    res = subprocess.run(
        ["pandoc", "-f", fmt, "-t", "html5", "--shift-heading-level-by=1", "--wrap=none"],
        input=md, capture_output=True, text=True, check=True)
    return res.stdout


def merge_table_groups(body: str) -> str:
    """Empty first cells continue the category above: turn them into a rowspan."""
    def fix_tbody(m):
        rows = re.findall(r"<tr[^>]*>.*?</tr>", m.group(0), flags=re.S)
        new, head, span = [], None, 0

        def flush():
            if head is not None:
                new[head] = new[head].replace("<td", f'<th scope="rowgroup" rowspan="{span}"', 1) \
                                     .replace("</td>", "</th>", 1)
        for row in rows:
            if re.search(r"<tr[^>]*>\s*<td[^>]*>\s*</td>", row) and head is not None:
                new.append(re.sub(r"(<tr[^>]*>)\s*<td[^>]*>\s*</td>", r"\1", row, count=1))
                span += 1
            else:
                flush()
                new.append(row)
                head, span = len(new) - 1, 1
        flush()
        return "<tbody>\n" + "\n".join(new) + "\n</tbody>"
    return re.sub(r"<tbody>.*?</tbody>", fix_tbody, body, flags=re.S)


def mark_chinese(body: str) -> str:
    # 1. Paragraphs that are entirely Chinese (source lines of block quotes).
    def para(m):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        if re.search(f"[{HAN}]", text) and not LATIN.search(html.unescape(text)):
            return f'<p class="zh zh-line" lang="zh-Hant">{m.group(2)}</p>'
        return m.group(0)
    body = re.sub(r"<p( [^>]*)?>(.*?)</p>", para, body, flags=re.S)

    # 2. Inline runs of Chinese in running text (with the space before them).
    parts = re.split(r"(<[^>]+>)", body)
    inside_zh_line = False
    for i, part in enumerate(parts):
        if part.startswith("<"):
            if part.startswith('<p class="zh zh-line"'):
                inside_zh_line = True
            elif part == "</p>":
                inside_zh_line = False
            continue
        if inside_zh_line or not part:
            continue
        at_block_start = i > 0 and re.match(r"<(p|li)\b", parts[i - 1])

        def wrap(m, at_block_start=at_block_start, part=part):
            run, end = m.group(0), m.end()
            # A note that opens with a Chinese quotation: hide its comma too.
            if at_block_start and m.start() == 0 and part[end:end + 2] == ", ":
                return f'<span class="zh" lang="zh-Hant">{run}, </span>\x00'
            return f'<span class="zh" lang="zh-Hant">{run}</span>'
        new = ZH_RUN.sub(wrap, part)
        parts[i] = new.replace("\x00, ", "")
    return "".join(parts)


def french_spaces(body: str) -> str:
    """Non-breaking spaces inside « » and before ; : ! ? (text nodes only).

    Only existing spaces are converted, so URLs, times and English
    punctuation (no space before the mark) are left alone.
    """
    nbsp, thin = "\u00a0", "\u202f"
    parts = re.split(r"(<[^>]+>)", body)
    for i, part in enumerate(parts):
        if part.startswith("<") or not part:
            continue
        part = re.sub(r"«[ \u00a0\u202f]", "«" + nbsp, part)
        part = re.sub(r"[ \u00a0\u202f]([»:])", nbsp + r"\1", part)
        part = re.sub(r"[ \u00a0\u202f]([;!?])", thin + r"\1", part)
        parts[i] = part
    return "".join(parts)


def postprocess(body: str) -> str:
    body = merge_table_groups(body)
    body = mark_chinese(body)
    body = french_spaces(body)
    body = re.sub(r"<p>(<strong>(?:Figure|Tableau)\b)", r'<p class="caption">\1', body)
    body = body.replace("<img ", '<img loading="eager" decoding="async" ')
    body = re.sub(r'(<section[^>]*class="footnotes[^>]*>)\s*<hr ?/?>', r"\1\n<h2>Notes</h2>", body)
    return body


def check_script(n_slides: int):
    if not SCRIPT.exists():
        return
    cues = [int(n) for n in re.findall(r"▶ DIAPO (\d+)", SCRIPT.read_text(encoding="utf-8"))]
    expected = list(range(1, n_slides + 1))
    if cues != expected:
        print(f"warning: script cues {cues} do not match article slides 1..{n_slides}")
    else:
        print(f"script cues match: {n_slides} slides")


PAGE = Path(__file__).with_name("template.html")


def main():
    md, labels = preprocess(ARTICLE.read_text(encoding="utf-8"))
    body = postprocess(pandoc(md))
    header = ""
    if TITLE:
        header = f"<header><h1>{french_spaces(html.escape(TITLE))}</h1>"
        header += f'<p class="author">{html.escape(AUTHOR)}</p>' if AUTHOR else ""
        header += f'<p class="event">{french_spaces(html.escape(EVENT))}</p>' if EVENT else ""
        header += "</header>"
    page = PAGE.read_text(encoding="utf-8")
    page = page.replace("{{TITLE}}", french_spaces(html.escape(TITLE or "Article")))
    page = page.replace("{{HEADER}}", header).replace("{{BODY}}", body)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.name}: {len(labels)} slides")
    check_script(len(labels))


if __name__ == "__main__":
    main()
