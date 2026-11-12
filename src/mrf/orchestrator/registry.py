"""Which implementation the orchestrator uses for each Protocol.

Concrete classes are wired explicitly in ``_implementations``. Missing implementations fail at startup.
No-argument constructors keep assembly simple; tests may override individual slots.

    slot              module:Class                                   owner
    classifier        mrf.agents.classify.agent:ClassifierAgent      A1
    doc_writer        mrf.agents.doc.agent:DocAgent                  A3
    rater             mrf.rating.rater:DocRater                      A3
    rebuilder         mrf.agents.rebuild.agent:RebuildAgent          A2
    runner            mrf.agents.rebuild.runner:ModelRunnerImpl      A2
    report_builder    mrf.reporting.builder:ReportBuilderImpl        A3
    quality_checker   mrf.monitoring.quality:QualityCheckerImpl      A4
    monitoring        mrf.monitoring.registrar:MonitoringRegistrarImpl  A4

Local opt-in stubs: ``MRF_STUBS=all`` or ``MRF_STUBS=rater,rebuilder`` (forbidden in dev/demo).
Tests: ``Registry.stubs(rater=StubRater(pass_on_attempt=3))``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Any

from mrf.config import get_settings
from mrf.contracts.agents import (
    Classifier,
    DataQualityChecker,
    DocWriter,
    ModelRunner,
    MonitoringRegistrar,
    Rater,
    Rebuilder,
    ReportBuilder,
)
from mrf.core import MRFCode, MRFError
from mrf.orchestrator import stubs


def _implementations() -> dict[str, type[Any]]:
    """Explicit composition root. Missing production code is an import error, never a stub."""
    from mrf.agents.classify.agent import ClassifierAgent
    from mrf.agents.doc.agent import DocAgent
    from mrf.agents.rebuild.agent import RebuildAgent
    from mrf.agents.rebuild.runner import ModelRunnerImpl
    from mrf.monitoring.quality import QualityCheckerImpl
    from mrf.monitoring.registrar import MonitoringRegistrarImpl
    from mrf.rating.rater import DocRater
    from mrf.reporting.builder import ReportBuilderImpl

    return {
        "classifier": ClassifierAgent, "doc_writer": DocAgent, "rater": DocRater,
        "rebuilder": RebuildAgent, "runner": ModelRunnerImpl, "report_builder": ReportBuilderImpl,
        "quality_checker": QualityCheckerImpl, "monitoring": MonitoringRegistrarImpl,
    }

STUBS: dict[str, type[Any]] = {
    "classifier": stubs.StubClassifier,
    "doc_writer": stubs.StubDocWriter,
    "rater": stubs.StubRater,
    "rebuilder": stubs.StubRebuilder,
    "runner": stubs.StubRunner,
    "report_builder": stubs.StubReportBuilder,
    "quality_checker": stubs.StubQualityChecker,
    "monitoring": stubs.StubMonitoringRegistrar,
}


@dataclass
class Registry:
    classifier: Classifier
    doc_writer: DocWriter
    rater: Rater
    rebuilder: Rebuilder
    runner: ModelRunner
    report_builder: ReportBuilder
    quality_checker: DataQualityChecker
    monitoring: MonitoringRegistrar

    @classmethod
    def stubs(cls, **overrides: Any) -> Registry:
        values = {f.name: STUBS[f.name]() for f in fields(cls)}
        values.update(overrides)
        return cls(**values)

    @classmethod
    def discover(cls, **overrides: Any) -> Registry:
        forced = {s.strip() for s in os.environ.get("MRF_STUBS", "").split(",") if s.strip()}
        if forced and get_settings().env != "local":
            raise MRFError(MRFCode.INVALID_STATE, "MRF_STUBS is only allowed in the local environment")
        unknown = forced - set(STUBS) - {"all"}
        if unknown:
            raise MRFError(MRFCode.INPUT_BODY, f"unknown stub slots: {', '.join(sorted(unknown))}")
        implementations = {} if "all" in forced else _implementations()
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in overrides:
                values[f.name] = overrides[f.name]
            elif "all" in forced or f.name in forced:
                values[f.name] = STUBS[f.name]()
            else:
                values[f.name] = implementations[f.name]()
        return cls(**values)

    def describe(self) -> dict[str, str]:
        return {f.name: type(getattr(self, f.name)).__qualname__ for f in fields(self)}
