"""Persistence. Owner: A1.

Repository protocol over JSON documents, one collection per entity
(models, pipelines, jobs, reviews, documents, ratings, rebuilds, datasets, runs, reports,
alerts, schedules, audit, idempotency). Backends: SQLite (local/CI) and Cosmos DB (cloud),
selected by MRF_STORAGE_BACKEND. Blob store: local filesystem or Azure Blob.
Other modules use ``get_repo()`` / ``get_blobs()`` and never touch SQL or Cosmos directly.
"""
