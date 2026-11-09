"""Deterministic documentation checks (the 60 rule points and both veto flags). Owner: A3.

Pure functions, no I/O: :func:`evaluate` takes the Document, an independently built :class:`CodeContext`
(the rater re-parses the source itself) and a knowledge-base lookup. The documentation agent reuses the
number / variable helpers to vet LLM claims before it hands a draft in.

Statement ("claim") = one bullet, numbered item, table body row or paragraph line of a section. A claim is
evidenced when it carries at least one ``[E#]`` marker that points to an existing, verified Evidence entry.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from mrf.contracts.models import Document, Evidence
from mrf.rating.rubric import title

CITATION = re.compile(r"\[E(\d+)\]")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?(?![\w])")
#: references and dates that contain digits but are not quantities
_MASKS = (
    CITATION,
    re.compile(r"\b(?:SS|PS|CP|SR)\s?\d+/\d+\b"),  # SS1/23, PS6/23
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(r"\b[\w.-]+\.(?:sas|r|py|ipynb|csv|parquet|md|yaml|json)(?::\d+(?:-\d+)?)?\b", re.I),
    re.compile(r"`[^`]*`"),  # inline code: expressions copied from the source are checked as code, not prose
    re.compile(r"\blines?\s+\d+(?:\s*-\s*\d+)?", re.I),
)
_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_WORD = re.compile(r"[A-Za-z]{2,}")
_WS = re.compile(r"\s+")


# ---------------------------------------------------------------------------------------------- text helpers
def citations(text: str) -> list[int]:
    return [int(n) for n in CITATION.findall(text)]


def claims(section_md: str) -> list[str]:
    """Statements of a section: list items, table body rows and paragraph lines (headings excluded)."""
    lines = section_md.split("\n")
    out: list[str] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#") or _SEPARATOR.match(line):
            continue
        if line.startswith("|"):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if _SEPARATOR.match(nxt):  # table header row
                continue
        text = _LIST_MARK.sub("", line)
        if len(_WORD.findall(text)) < 2 and not CITATION.search(text):
            continue  # labels such as "**Variables**"
        out.append(text)
    return out


def _masked(text: str) -> str:
    for pattern in _MASKS:
        text = pattern.sub(" ", text)
    return text


def number_tokens(text: str, small_integer_limit: int = 10) -> list[str]:
    """Numbers in prose that must be traceable to evidence (small integers and references excluded)."""
    out: list[str] = []
    for token in NUMBER.findall(_masked(text)):
        value = parse_number(token)
        if value is None:
            continue
        is_int = re.fullmatch(r"[-+]?[\d,]+", token) is not None
        if is_int and abs(value) <= small_integer_limit:
            continue
        out.append(token)
    return out


def parse_number(token: str) -> float | None:
    raw = token.replace(",", "").rstrip("%")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value


def numbers_in(texts: Iterable[str | None]) -> list[float]:
    """Every number in the given texts (no exclusions) - the allowed set for :func:`number_supported`."""
    values: list[float] = []
    for text in texts:
        if not text:
            continue
        for token in NUMBER.findall(text):
            value = parse_number(token)
            if value is not None:
                values.append(value)
                if token.endswith("%"):
                    values.append(value / 100)
    return values


def number_supported(token: str, allowed: Iterable[float]) -> bool:
    """True when ``token`` equals an allowed value, or the allowed value rounded to the token's precision.
    A percentage also matches its fraction (12.5% <-> 0.125)."""
    value = parse_number(token)
    if value is None:
        return True
    raw = token.replace(",", "").rstrip("%")
    mantissa = re.split(r"[eE]", raw)[0]
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    targets = [value, value / 100] if token.endswith("%") else [value]
    for a in allowed:
        for t in targets:
            if math.isclose(a, t, rel_tol=1e-9, abs_tol=1e-12):
                return True
            if "e" not in raw.lower() and round(a, decimals) == round(t, decimals):
                return True
    return False


def identifiers(texts: Iterable[str | None]) -> set[str]:
    return {tok for text in texts if text for tok in IDENTIFIER.findall(text)}


def normalise(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


# ---------------------------------------------------------------------------------------------- inputs / outputs
@dataclass
class CodeContext:
    """What the rater learns independently of the writer: parsed source and registered datasets."""

    model_id: str = ""
    features: list[str] = field(default_factory=list)
    target: str | None = None
    class_variables: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # filename -> source text
    dataset_columns: set[str] = field(default_factory=set)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> set[str]:
        return identifiers(self.sources.values()) | set(self.features) | ({self.target} if self.target else set())


@dataclass
class RuleResult:
    scores: dict[str, float]
    veto: set[str]
    comments: list[str]
    stats: dict[str, Any]

    @property
    def total(self) -> float:
        return round(sum(self.scores.values()), 2)


KbLookup = Callable[[str], str | None]  # chunk id -> chunk text (None when unknown)


def verify_evidence(ev: Evidence, code: CodeContext, kb_text: KbLookup) -> str | None:
    """None when the evidence checks out, else the reason. Code and KB quotes are compared with their source;
    tool / data / human evidence cannot be re-derived here and is accepted."""
    if ev.source == "code":
        filename, _, span = ev.ref.partition(":")
        text = code.sources.get(filename)
        if text is None or not ev.quote:
            return None  # repository files (config, orchestrator) or no quote: nothing to compare
        lines = text.split("\n")
        if re.fullmatch(r"\d+(-\d+)?", span or ""):
            a, _, b = span.partition("-")
            lo, hi = int(a), int(b or a)
            if not 1 <= lo <= hi <= len(lines):
                return f"line range {span} is outside {filename} ({len(lines)} lines)"
            text = "\n".join(lines[lo - 1 : hi])
        return None if normalise(ev.quote.removesuffix("...")) in normalise(text) else "quote not found in the code"
    if ev.source == "kb":
        chunk = kb_text(ev.ref)
        if chunk is None:
            return "unknown knowledge-base chunk"
        if ev.quote and normalise(ev.quote.removesuffix("...")) not in normalise(chunk):
            return "quote not found in the knowledge-base chunk"
    return None


# ---------------------------------------------------------------------------------------------- evaluation
def evaluate(
    document: Document,
    code: CodeContext,
    rubric: dict[str, Any],
    kb_text: KbLookup,
) -> RuleResult:
    rules = rubric["rule_checks"]
    required: list[str] = list(rules["section_completeness"]["required_sections"])
    min_words = int(rules["section_completeness"].get("min_words", 15))
    small_int = int(rubric.get("numbers", {}).get("small_integer_limit", 10))
    comments: list[str] = []
    veto: set[str] = set()

    # evidence integrity
    invalid: dict[int, str] = {}
    for i, ev in enumerate(document.evidence, start=1):
        reason = verify_evidence(ev, code, kb_text)
        if reason:
            invalid[i] = reason
            comments.append(f"Evidence [E{i}] ({ev.source}: {ev.ref}) failed verification: {reason}. Fix or remove it.")
    valid = {i for i in range(1, len(document.evidence) + 1) if i not in invalid}
    valid_quotes = [document.evidence[i - 1].quote for i in sorted(valid)]
    allowed_numbers = numbers_in([*valid_quotes, *code.sources.values()])
    allowed_names = code.tokens | code.dataset_columns | identifiers(valid_quotes) | {code.model_id}

    # 1. section completeness
    per_section: dict[str, float] = {}
    for sid in required:
        body = document.sections.get(sid, "")
        words = len(_WORD.findall(CITATION.sub(" ", body)))
        has_valid_marker = any(n in valid for n in citations(body))
        if not body.strip():
            per_section[sid] = 0.0
            comments.append(
                f"Add the '{title(sid)}' section ({sid}) with at least {min_words} words of evidenced statements [E#]."
            )
        elif words < min_words or not has_valid_marker:
            per_section[sid] = 0.5
            comments.append(
                f"Expand '{title(sid)}': {words} words, {'no' if not has_valid_marker else 'some'} valid evidence "
                f"markers - add evidenced statements."
            )
        else:
            per_section[sid] = 1.0
    w_sec = float(rules["section_completeness"]["weight"])
    completeness = w_sec * sum(per_section.values()) / len(required) if required else w_sec

    # 2. evidence coverage + fabricated numbers / variables (all sections, including extra ones)
    total = cited = 0
    uncited: list[tuple[str, str]] = []
    bad_numbers: list[tuple[str, str]] = []
    bad_names: set[str] = set()
    for sid, body in document.sections.items():
        for claim in claims(body):
            total += 1
            marks = citations(claim)
            if any(n in valid for n in marks):
                cited += 1
            else:
                uncited.append((sid, claim))
            for n in marks:
                if n > len(document.evidence):
                    comments.append(f"[E{n}] in '{title(sid)}' does not exist in the evidence list.")
            for token in number_tokens(claim, small_int):
                if not number_supported(token, allowed_numbers):
                    bad_numbers.append((sid, token))
            bad_names.update(name for name in BACKTICKED.findall(claim) if name not in allowed_names)
    for sid, claim in uncited[:3]:
        comments.append(f"In '{title(sid)}', cite evidence for: \"{claim[:90]}\" - or remove the statement.")
    if len(uncited) > 3:
        comments.append(f"{len(uncited) - 3} more statements have no valid evidence marker.")
    if bad_numbers:
        veto.add("fabricated_number")
        listed = ", ".join(f"{tok} ({title(sid)})" for sid, tok in bad_numbers[:5])
        comments.append(
            f"Numbers not found in any verified evidence: {listed}. Copy numbers from tool outputs or remove them "
            "(fabricated_number)."
        )
    if bad_names:
        veto.add("fabricated_variable")
        comments.append(
            "Variables not in the source code or dataset: "
            + ", ".join(f"`{n}`" for n in sorted(bad_names))
            + ". Remove them (fabricated_variable)."
        )
    w_cov = float(rules["evidence_coverage"]["weight"])
    coverage = w_cov * cited / total if total else 0.0

    # 3. variable consistency
    documented = {n for body in document.sections.values() for n in BACKTICKED.findall(body)}
    expected = set(code.features)
    w_var = float(rules["variable_consistency"]["weight"])
    if expected:
        missing = sorted(expected - documented)
        consistency = w_var * (len(expected) - len(missing)) / len(expected)
        if missing:
            comments.append(
                "Document the model variables found by parse_code: "
                + ", ".join(f"`{m}`" for m in missing)
                + " (data section variable table)."
            )
    else:
        consistency = 0.0
        comments.append(
            "The rater could not extract model variables from the source code "
            f"({'; '.join(code.parse_errors) or 'no features found'}); variable consistency scored 0."
        )

    return RuleResult(
        scores={
            "section_completeness": round(completeness, 2),
            "evidence_coverage": round(coverage, 2),
            "variable_consistency": round(consistency, 2),
        },
        veto=veto,
        comments=comments,
        stats={
            "claims": total,
            "cited_claims": cited,
            "invalid_evidence": sorted(invalid),
            "unsupported_numbers": [tok for _, tok in bad_numbers],
            "fabricated_variables": sorted(bad_names),
            "sections": per_section,
        },
    )
