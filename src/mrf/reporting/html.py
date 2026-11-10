"""Small, dependency-free markdown -> HTML for documents served with ``?format=html``. Owner: A3.

Covers what the documentation agent writes: headings, bullet lists, pipe tables, paragraphs, ``inline code``
and **bold**. All text is HTML-escaped first, so document content can never inject markup.
"""

from __future__ import annotations

import html
import re

_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LIST_ITEM = re.compile(r"^\s*[-*+]\s+")

PAGE_CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:980px;margin:32px auto;padding:0 20px;
color:#1d2433;line-height:1.5}
h1{font-size:1.6em;border-bottom:2px solid #1d2433;padding-bottom:6px}h2{margin-top:1.6em;font-size:1.25em}
table{border-collapse:collapse;margin:12px 0;width:100%}th,td{border:1px solid #c9ced8;padding:5px 8px;
text-align:left;vertical-align:top}th{background:#eef1f6}code{background:#f2f4f8;padding:1px 4px;border-radius:3px}
li{margin:3px 0}.muted{color:#5b6475;font-size:.9em}
"""


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def markdown_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if not stripped:
            i += 1
        elif heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
        elif stripped.startswith("|"):
            rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            has_header = len(rows) > 1 and bool(_SEPARATOR.match(rows[1]))
            body = rows[2:] if has_header else rows
            table = ["<table>"]
            if has_header:
                table.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in _cells(rows[0])) + "</tr>")
            table += ["<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(r)) + "</tr>" for r in body]
            out.append("\n".join([*table, "</table>"]))
        elif re.match(r"^[-*+]\s+", stripped):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                item = _LIST_ITEM.sub("", lines[i])
                items.append(f"<li>{_inline(item)}</li>")
                i += 1
            out.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
            i += 1
    return "\n".join(out)


def html_page(title: str, body_html: str) -> str:
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f"<style>{PAGE_CSS}</style></head><body>\n{body_html}\n</body></html>\n"
    )
