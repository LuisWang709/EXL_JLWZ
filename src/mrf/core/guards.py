"""Input guards: personal data (MRF-1004) and prompt injection (MRF-1005). Owner: A1.

Everything a user uploads or types eventually reaches an LLM prompt (source code -> classifier / doc writer /
rebuilder; review comments -> ``ctx.feedback``), so it is screened once at the API edge.

Design rules:

* findings carry file, kind and line - never the matched value (the error must not leak the PII it found);
* high-precision patterns only, with checksums where one exists (Luhn, IBAN mod-97, PPSN mod-23), so numeric
  columns in data files do not trip the guard;
* e-mail addresses are only personal data in *data* files - an ``Author: x@bank.com`` header in legacy code is
  normal and must not block an upload;
* archives (.zip / .egp) are opened without extracting: member count and uncompressed size are capped
  (zip-bomb guard, MRF-1002) and text members are scanned like plain uploads.

Patterns and switches live in ``config/pipeline.yaml: guards``.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from mrf.config import get_policy, get_settings
from mrf.core.codes import MRFCode
from mrf.core.errors import MRFError

ARCHIVE_SUFFIXES = {".zip", ".egp"}
DATA_SUFFIXES = {".csv", ".json"}
TEXT_SUFFIXES = {".sas", ".r", ".py", ".ipynb", ".txt", ".json", ".yaml", ".yml", ".md", ".csv"}

_CARD = re.compile(r"(?<![\d.])\d{13,19}(?![\d.])")
_CARD_SPACED = re.compile(r"(?<![\d.])\d{4}(?:[ -]\d{4}){2}[ -]\d{1,7}(?![\d.])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_NINO = re.compile(r"\b(?!BG|GB|KN|NK|NT|TN|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
_PPSN = re.compile(r"\b(\d{7})([A-W])([A-IW]?)\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

DEFAULT_INJECTION = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions|prompts?|rules)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|system)\s+(?:instructions|prompts?|rules)",
    r"forget\s+(?:all\s+|your\s+)?(?:previous\s+)?instructions",
    r"you\s+are\s+now\s+(?:a|an|in|the)\b",
    r"(?:reveal|print|show|repeat|output)\s+(?:your|the)\s+(?:system\s+prompt|hidden\s+instructions)",
    r"<\|im_start\|>|<\|system\|>|\[/?INST\]|<<SYS>>",
    r"\b(?:give|assign|award|rate)\s+(?:this|the)\s+(?:document|model|doc(?:umentation)?)\s+(?:a\s+)?"
    r"(?:score|rating)\s+of\b",
    r"\bmark\s+(?:this|it|the\s+(?:document|model))\s+as\s+(?:passed|approved|compliant)\b",
]


@dataclass(frozen=True)
class Finding:
    kind: str
    where: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "where": self.where, "line": self.line}


# ------------------------------------------------------------------ checksums
def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _ppsn_ok(digits: str, check: str, second: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, range(8, 1, -1), strict=True))
    if second:
        total += (ord(second) - 64 if second != "W" else 0) * 9
    expected = total % 23
    return check == ("W" if expected == 0 else chr(64 + expected))


# ------------------------------------------------------------------ config
def _cfg() -> dict[str, Any]:
    cfg: dict[str, Any] = get_policy().get("guards") or {}
    return cfg


def _injection_patterns() -> list[re.Pattern[str]]:
    extra = [str(p) for p in (_cfg().get("injection_patterns_extra") or [])]
    return [re.compile(p, re.IGNORECASE) for p in [*DEFAULT_INJECTION, *extra]]


# ------------------------------------------------------------------ scanning
def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan_pii(text: str, where: str, *, data_file: bool = False) -> list[Finding]:
    found: list[Finding] = []
    for m in _CARD.finditer(text):
        if _luhn(m.group()):
            found.append(Finding("card_number", where, _line_of(text, m.start())))
    for m in _CARD_SPACED.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append(Finding("card_number", where, _line_of(text, m.start())))
    for m in _IBAN.finditer(text):
        if _iban_ok(m.group()):
            found.append(Finding("iban", where, _line_of(text, m.start())))
    for m in _NINO.finditer(text):
        found.append(Finding("uk_national_insurance_number", where, _line_of(text, m.start())))
    for m in _PPSN.finditer(text):
        if _ppsn_ok(*m.groups()):
            found.append(Finding("irish_ppsn", where, _line_of(text, m.start())))
    if data_file:
        for m in _EMAIL.finditer(text):
            found.append(Finding("email", where, _line_of(text, m.start())))
    return found


def scan_injection(text: str, where: str) -> list[Finding]:
    found: list[Finding] = []
    for pat in _injection_patterns():
        for m in pat.finditer(text):
            found.append(Finding("prompt_injection", where, _line_of(text, m.start())))
    return found


def _decode(data: bytes) -> str:
    limit = int(_cfg().get("scan_max_bytes", 5_000_000))
    return data[:limit].decode("utf-8", errors="replace")


def _archive_members(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    max_members = int(_cfg().get("archive_max_members", 500))
    max_total = int(_cfg().get("archive_max_uncompressed_mb", 100)) * 1024 * 1024
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise MRFError(MRFCode.INPUT_FILE_TYPE, f"'{filename}' is not a valid archive", field="files") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_members:
            raise MRFError(
                MRFCode.INPUT_FILE_SIZE, f"'{filename}' has {len(infos)} members (max {max_members})", field="files"
            )
        if sum(i.file_size for i in infos) > max_total:
            raise MRFError(MRFCode.INPUT_FILE_SIZE, f"'{filename}' expands beyond the archive size cap", field="files")
        members: list[tuple[str, bytes]] = []
        for info in infos:
            if PurePosixPath(info.filename).suffix.lower() in TEXT_SUFFIXES:
                members.append((f"{filename}!{info.filename}", zf.read(info)))
        return members


def scan_file(filename: str, data: bytes) -> list[Finding]:
    """All findings for one uploaded file (archives are opened and their text members scanned)."""
    cfg = _cfg()
    suffix = PurePosixPath(filename).suffix.lower()
    items = _archive_members(filename, data) if suffix in ARCHIVE_SUFFIXES else [(filename, data)]
    found: list[Finding] = []
    for where, blob in items:
        text = _decode(blob)
        is_data = PurePosixPath(where).suffix.lower() in DATA_SUFFIXES
        if cfg.get("pii", True):
            found += scan_pii(text, where, data_file=is_data)
        if cfg.get("prompt_injection", True):
            found += scan_injection(text, where)
    return found


def scan_text(text: str, where: str, *, pii: bool = True) -> list[Finding]:
    """Free-text fields (model name, description, review comments / edits)."""
    cfg = _cfg()
    found: list[Finding] = []
    if pii and cfg.get("pii", True):
        found += scan_pii(text, where)
    if cfg.get("prompt_injection", True):
        found += scan_injection(text, where)
    return found


def raise_on(findings: list[Finding], field: str | None = None) -> None:
    """Injection beats PII (it is the more dangerous one); the first matching code decides the response."""
    if not findings:
        return
    if not get_settings().guards_enabled:
        return
    injection = [f for f in findings if f.kind == "prompt_injection"]
    chosen = injection or findings
    code = MRFCode.INPUT_PROMPT_INJECTION if injection else MRFCode.INPUT_PERSONAL_DATA
    where = sorted({f.where for f in chosen})
    raise MRFError(
        code,
        f"{code.default_message}: {', '.join(where)[:300]}",
        field=field,
        detail={"findings": [f.as_dict() for f in chosen[:20]], "total": len(chosen)},
    )
