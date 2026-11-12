"""Which implementation the orchestrator uses for each Protocol.

Convention over configuration: put your class at the path below with a no-argument
constructor and it is picked up automatically - no edit to this file needed.
Until the module exists, the stub from ``stubs.py`` is used.

    slot              module:Class                                   owner
    classifier        mrf.agents.classify.agent:ClassifierAgent      A1
    doc_writer        mrf.agents.doc.agent:DocAgent                  A3
    rater             mrf.rating.rater:DocRater                      A3
    rebuilder         mrf.agents.rebuild.agent:RebuildAgent          A2
    runner            mrf.agents.rebuild.runner:ModelRunnerImpl      A2
    report_builder    mrf.reporting.builder:ReportBuilderImpl        A3
    quality_checker   mrf.monitoring.quality:QualityCheckerImpl      A4
    monitoring        mrf.monitoring.registrar:MonitoringRegistrarImpl  A4

Force stubs (e.g. CI, or while your module is half-done): ``MRF_STUBS=all`` or ``MRF_STUBS=rater,rebuilder``.
Tests: ``Registry.stubs(rater=StubRater(pass_on_attempt=3))``.
"""

from __future__ import annotations

import importlib
import logging
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

log = logging.getLogger(__name__)

IMPLEMENTATIONS: dict[str, str] = {
    "classifier": "mrf.agents.classify.agent:ClassifierAgent",
    "doc_writer": "mrf.agents.doc.agent:DocAgent",
    "rater": "mrf.rating.rater:DocRater",
    "rebuilder": "mrf.agents.rebuild.agent:RebuildAgent",
    "runner": "mrf.agents.rebuild.runner:ModelRunnerImpl",
    "report_builder": "mrf.reporting.builder:ReportBuilderImpl",
    "quality_checker": "mrf.monitoring.quality:QualityCheckerImpl",
    "monitoring": "mrf.monitoring.registrar:MonitoringRegistrarImpl",
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
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in overrides:
                values[f.name] = overrides[f.name]
            elif "all" in forced or f.name in forced:
                values[f.name] = STUBS[f.name]()
            else:
                values[f.name] = _load(f.name)
        return cls(**values)

    def describe(self) -> dict[str, str]:
        return {f.name: type(getattr(self, f.name)).__qualname__ for f in fields(self)}


def _load(slot: str) -> Any:
    module_name, _, class_name = IMPLEMENTATIONS[slot].partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):  # the module itself is missing -> not written yet
            if get_settings().env != "local":
                raise MRFError(MRFCode.INVALID_STATE, f"required agent '{slot}' is unavailable") from exc
            log.info("registry: %s not implemented yet, using stub", slot)
            return STUBS[slot]()
        raise  # a dependency inside the module is missing: surface it
    impl = getattr(module, class_name, None)
    if impl is None:
        if get_settings().env != "local":
            raise MRFError(MRFCode.INVALID_STATE, f"required agent '{slot}' is unavailable")
        log.warning("registry: %s has no %s, using stub", module_name, class_name)
        return STUBS[slot]()
    return impl()
