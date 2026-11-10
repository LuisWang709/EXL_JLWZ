"""Number ledger: every number in a report is rendered from a named source value and re-checked afterwards.

Templates never print a raw number. They call ``num("performance.gini", ".3f")``, which formats the value
stored under that key in ``facts`` and wraps it in ``<span class="num" data-key=... data-spec=...>``.
:func:`check_numbers` then (1) re-formats every span from ``facts`` and compares it with what is shown, and
(2) strips the ``<head>``, all spans, labels / ids / timestamps (``<span class="meta">``) and markup and fails on
any number left in the text - a number typed into a template or copied from an unknown place. Reports must show
0 mismatches.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from markupsafe import Markup

from mrf.rating.checks import number_tokens

_NUM_SPAN = re.compile(r'<span class="num" data-key="([^"]+)" data-spec="([^"]*)">([^<]*)</span>')
_META_SPAN = re.compile(r'<span class="meta">.*?</span>', re.S)
_HEAD = re.compile(r"<head>.*?</head>", re.S)
_TAG = re.compile(r"<[^>]+>")


def fmt(value: Any, spec: str) -> str:
    if spec == "d":
        return format(int(value), "d")
    return format(float(value), spec)


@dataclass
class Ledger:
    facts: dict[str, Any]
    sources: dict[str, str] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)

    def num(self, key: str, spec: str = ".3f") -> Markup:
        value = self.facts.get(key)
        if value is None:
            return Markup('<span class="na">n/a</span>')
        text = fmt(value, spec)
        self.entries.append({"key": key, "value": value, "text": text, "source": self.sources.get(key, "")})
        return Markup('<span class="num" data-key="{}" data-spec="{}">{}</span>').format(key, spec, text)

    def has(self, key: str) -> bool:
        return self.facts.get(key) is not None


def check_numbers(page: str, facts: dict[str, Any]) -> dict[str, Any]:
    mismatched: list[dict[str, Any]] = []
    count = 0
    for key, spec, shown in _NUM_SPAN.findall(page):
        count += 1
        key, spec, shown = html.unescape(key), html.unescape(spec), html.unescape(shown)
        value = facts.get(key)
        expected = fmt(value, spec) if value is not None else None
        if expected != shown:
            mismatched.append({"key": key, "shown": shown, "source_value": value})
    rest = _HEAD.sub(" ", page)
    rest = _NUM_SPAN.sub(" ", rest)
    rest = _META_SPAN.sub(" ", rest)
    rest = html.unescape(_TAG.sub(" ", rest))
    untraceable = number_tokens(rest, small_integer_limit=-1)
    return {
        "numbers": count,
        "mismatched": mismatched,
        "untraceable": untraceable,
        "passed": not mismatched and not untraceable,
    }
