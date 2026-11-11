# docker (owner: A4)

| File | Image | Notes |
| --- | --- | --- |
| `Dockerfile.api` | API + `/mcp` + job workers (`uvicorn mrf.api.app:app`, port 8000) | **one replica only** - the job queue is in-process |
| `Dockerfile.ui` | Streamlit (planned, 11/10) | talks to the API only |

Local check:

```bash
docker build -f docker/Dockerfile.api -t mrf-api:local .
export MRF_API_KEY=<any local value>
docker run --rm -p 8000:8000 -e MRF_API_KEY -e MRF_LLM_PROVIDER=mock mrf-api:local
curl -s localhost:8000/healthz
curl -s localhost:8000/readyz
curl -s -H "X-API-Key: $MRF_API_KEY" localhost:8000/api/v1/models
```

Building on an Apple-silicon Mac for Azure: add `--platform linux/amd64`. CD builds on the GitHub runner and pushes
to ACR (`az acr build` / ACR Tasks is not allowed on Azure for Students).

Paths inside the container: `/data` (persistent volume: blobs, reports, `mlruns/`) and `/state`
(local disk: `MRF_SQLITE_PATH`, `MRF_CHECKPOINT_PATH`). SQLite runs in WAL mode, which does not work on
network file systems, so `/state` must not be an Azure Files share.

## UI image

`docker/Dockerfile.ui` - Streamlit (`src/mrf/ui`), port 8501, talks only to the API:

```bash
docker build -f docker/Dockerfile.ui -t mrf-ui:local .
docker run --rm -p 8501:8501 -e API_BASE_URL=http://host.docker.internal:8000 mrf-ui:local
```

Without `MRF_API_KEY` in the container the sign-in page also asks for the API URL; with it, only for the key.
