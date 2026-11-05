"""One router per resource. Endpoint list + owners: openapi.yaml and docs/team/*.md.

Each router file currently only declares its prefix; owners add path operations that
return :mod:`mrf.core.envelope` objects and match openapi.yaml exactly.
"""

from fastapi import APIRouter

from mrf.api.routers import (
    datasets,
    documents,
    health,
    jobs,
    models,
    monitoring,
    pipelines,
    rebuilds,
    reports,
    reviews,
    runs,
)

ROUTERS: list[APIRouter] = [
    pipelines.router,
    models.router,
    documents.router,
    rebuilds.router,
    datasets.router,
    runs.router,
    reports.router,
    reviews.router,
    monitoring.router,
    jobs.router,
]

__all__ = ["ROUTERS", "health"]
