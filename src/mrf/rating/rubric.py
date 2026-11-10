"""Rubric loading and the fixed SS1/23-aligned section list. Owner: A3."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RUBRIC_PATH = Path(__file__).with_name("rubric.yaml")

#: section id -> heading used in the rendered document (ids are fixed by rubric.yaml)
SECTION_TITLES: dict[str, str] = {
    "purpose_and_use": "Purpose and use",
    "data": "Data",
    "methodology": "Methodology",
    "assumptions_and_limitations": "Assumptions and limitations",
    "performance": "Performance",
    "implementation": "Implementation",
    "monitoring": "Monitoring",
    "governance": "Governance",
}


@lru_cache
def load_rubric(path: Path = RUBRIC_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def required_sections() -> list[str]:
    return list(load_rubric()["rule_checks"]["section_completeness"]["required_sections"])


def title(section_id: str) -> str:
    return SECTION_TITLES.get(section_id, section_id.replace("_", " ").capitalize())
