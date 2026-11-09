"""OpenTelemetry / App Insights wiring. Owner: A1 (requested by A4).

* ``configure()`` - called once by the app factory: when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set and
  the ``azure`` extra is installed, calls ``configure_azure_monitor()`` (traces, logs, metrics to App Insights).
* ``span(name, **attrs)`` - a span per pipeline step (``mrf.node.<name>``); a no-op without OpenTelemetry.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)
_configured = False


def configure() -> bool:
    global _configured
    if _configured:
        return True
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        log.warning("APPLICATIONINSIGHTS_CONNECTION_STRING set but azure-monitor-opentelemetry missing ('azure' extra)")
        return False
    configure_azure_monitor(logger_name="mrf")
    _configured = True
    log.info("App Insights telemetry enabled")
    return True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    try:
        from opentelemetry import trace
    except ImportError:
        yield None
        return
    tracer = trace.get_tracer("mrf")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(
                    f"mrf.{key}", value if isinstance(value, str | int | float | bool) else str(value)
                )
        yield current


def event(name: str, **attributes: Any) -> None:
    """Attach an event (e.g. a state transition) to the current span."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    clean = {
        f"mrf.{k}": v if isinstance(v, str | int | float | bool) else str(v)
        for k, v in attributes.items()
        if v is not None
    }
    trace.get_current_span().add_event(name, clean)
