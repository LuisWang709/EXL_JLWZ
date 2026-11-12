# infra (owner: A4)

Bicep for Team A on Azure for Students (region **swedencentral**, the one our subscription allows).

| Resource group | File | Contents |
| --- | --- | --- |
| `rg-mrf-a-shared` | `shared.bicep` + portal | ACR (Basic), `id-mrf-github` (GitHub OIDC identity, AcrPush), Cosmos DB free tier (one database per environment), Azure OpenAI resource + model deployment (created in the portal) - survives deleting dev |
| `rg-mrf-a-dev` / `rg-mrf-a-demo` | `main.bicep` + `params/<env>.bicepparam` | Log Analytics + App Insights, storage (Azure Files `/data`), Key Vault, app identity, Container Apps env, `mrf-api-<env>`, optional `mrf-ui-<env>`, `mrf-monitor-<env>` timer job |

Design constraints (from A1's runtime):
- **`mrf-api` has exactly one replica** - the job queue runs in-process.
- Business data lives in **Cosmos** (`mrf-dev` / `mrf-demo` databases, containers = A1's `REQUIRED_CONTAINERS`,
  app identity has the data-plane "Built-in Data Contributor" role). LangGraph checkpoints stay on `/state`
  (EmptyDir); A1's checkpoint-loss recovery re-enters a pipeline from the stored state after a restart.
- `/data` (Azure Files): blobs, reports, `mlruns/`.
- LLM: **Azure OpenAI with managed identity** by default (`MRF_LLM_PROVIDER=azure_openai`, no key; the app identity
  gets "Cognitive Services OpenAI User"). Name the deployment after the model (`gpt-5-mini`) so the wrapper drops
  `temperature` for reasoning models. DeepSeek instead: `LLM_PROVIDER=openai LLM_MODEL=deepseek-chat
  LLM_BASE_URL=https://api.deepseek.com LLM_API_KEY=...`.
- Secrets never live in files: Bicep receives them as secure parameters read from your shell environment and
  stores them in Key Vault; the apps read them through their managed identity.

## First deployment

The step-by-step tutorial (portal screens, checks, troubleshooting) is the team doc "Azure 部署操作手册";
the commands in short:

```bash
az login && az account set --subscription "<Azure for Students>" && az bicep install

# shared: ACR, GitHub identity, Cosmos free tier
az group create -n rg-mrf-a-shared -l swedencentral
az deployment group create -g rg-mrf-a-shared -f infra/shared.bicep -o none
export ACR_NAME=$(az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.acrName.value -o tsv)
export COSMOS_ACCOUNT=$(az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.cosmosAccountName.value -o tsv)
export GITHUB_PRINCIPAL_ID=$(az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.githubPrincipalId.value -o tsv)

# Azure OpenAI: create the resource in rg-mrf-a-shared in the portal, deploy gpt-5-mini named "gpt-5-mini"
export AOAI_NAME=<resource name>

# first image. ACR Tasks (az acr build) is not allowed on Azure for Students -> build with Docker and push
# (or let cd-dev build it: it pushes mrf-api:<sha> and skips the deploy while dev does not exist yet)
az acr login -n "$ACR_NAME"
docker buildx build --platform linux/amd64 -f docker/Dockerfile.api -t "$ACR_NAME.azurecr.io/mrf-api:bootstrap" --push .
export API_IMAGE="$ACR_NAME.azurecr.io/mrf-api:bootstrap"

# secrets / ids
export MRF_API_KEY=$(openssl rand -hex 24)        # keep it; GitHub secret MRF_DEV_API_KEY
export ADMIN_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)

# dev
az deployment group what-if -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam
az deployment group create  -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam -o none
API=$(az deployment group show -g rg-mrf-a-dev -n main --query properties.outputs.apiUrl.value -o tsv)
curl -s "$API/healthz"; curl -s "$API/readyz"; curl -s -H "X-API-Key: $MRF_API_KEY" "$API/api/v1/models"
```

Demo is the same with `rg-mrf-a-demo`, `params/demo.bicepparam` and its **own** `MRF_API_KEY`.

### Adding the UI (once)

`cd-dev` builds and pushes `mrf-ui:<sha>` on every merge but only *updates* an existing UI app. Create it once by
re-running the dev deployment with the current API image and a UI image:

```bash
export API_IMAGE=$(az containerapp show -n mrf-api-dev -g rg-mrf-a-dev --query 'properties.template.containers[0].image' -o tsv)
export UI_IMAGE="${API_IMAGE/mrf-api/mrf-ui}"     # same commit
az deployment group create -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam -o none
az deployment group show -g rg-mrf-a-dev -n main --query properties.outputs.uiUrl.value -o tsv
```

The UI asks for the API key at sign-in (the container holds it, so the public URL alone is not enough).

## GitHub settings for CD (repo Settings -> Secrets and variables -> Actions)

| Kind | Name | Value |
| --- | --- | --- |
| secret | `AZURE_CLIENT_ID` | `az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.githubClientId.value -o tsv` |
| secret | `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| secret | `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| secret | `MRF_DEV_API_KEY` / `MRF_DEMO_API_KEY` | the `MRF_API_KEY` you used for that environment |
| variable | `ACR_NAME` | `echo $ACR_NAME` |

Then `cd-dev.yml` deploys every green `main`; `cd-demo.yml` is run by hand with a tag.

## Nightly real-LLM evaluation

The `nightly-eval` workflow evaluates M001 against the existing dev API and uploads raw evidence plus the report.
It refuses mock/unknown providers and fails if the pipeline fails or escalates. Set `vars.MRF_DEV_API_URL`,
`secrets.MRF_DEV_API_KEY`, and (after the data handoff) `vars.MRF_EVAL_M001_DATASETS` to space-separated dev dataset
IDs. Start it manually first. `vars.NIGHTLY_EVAL_ENABLED=true` enables the daily schedule; leave it unset until
the real LLM configuration and budget are agreed. Automatic H1/H2 decisions carry `evaluation-harness` as actor
and are evaluation events, not an independent approval. Do not run this on the production/demo inventory.

## Optional Azure Blob storage

Azure Files remains the default. To use the existing private `mrf` Blob container, set `MRF_BLOB_ACCOUNT_URL` to
the storage account's HTTPS endpoint and `MRF_BLOB_CONTAINER=mrf`. The existing Bicep grants the app identity
Storage Blob Data Contributor. The adapter uses managed identity, returns private artifact URLs, and downloads
file snapshots under `MRF_DATA_DIR/blob-cache` for pandas-based readers. Provision the container before enabling
the adapter. Source: [Azure SDK ContainerClient](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.containerclient?view=azure-python).
Existing `file://` references remain tied to Azure Files: retain that store or perform an explicit migration
before switching an environment that already contains records. No automatic migration is attempted.

MLflow defaults to SQLite under `MRF_DATA_DIR/mlflow.db` (the deprecated file store is not selected by the
Dockerfile). An explicit `MLFLOW_TRACKING_URI` overrides this with a tracking server or another supported store.

## When things go wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| `RequestDisallowedByAzure` | region outside the student policy | keep everything in swedencentral |
| app creation fails pulling the image (`UNAUTHORIZED`) | the AcrPull role was not effective yet | wait 2-3 minutes, run the same `az deployment group create` again |
| Key Vault name conflict after deleting a group | soft-deleted vault still reserved (7 days) | `az keyvault purge -n <name>` |
| `/readyz` says `data_dir: error` | the Azure Files mount is not writable for uid 10001 | tell A4; workaround: point `MRF_DATA_DIR` to `/state` (not persistent) |
| `/readyz` says `llm_config: missing AZURE_OPENAI_ENDPOINT` | `AOAI_NAME` was empty at deploy time | export it and redeploy |
| LLM calls fail with 401/403 | the "Cognitive Services OpenAI User" role is not effective yet | wait 5 minutes |
| LLM calls fail with `Unsupported parameter/value` | deployment name does not start with the model name | set `MRF_LLM_REASONING=true` on the app, or rename the deployment |
| `Cosmos container ... does not exist` | `COSMOS_ACCOUNT` was empty at deploy time, or a new collection was added | redeploy; new collections must be added to `modules/cosmos-db.bicep` |
| Cosmos free tier error on `shared.bicep` | the subscription already has a free-tier account | deploy with `-p deployCosmos=false` and tell A4 |
| logs | - | `az containerapp logs show -n mrf-api-dev -g rg-mrf-a-dev --follow` |
| save money at night (dev) | one replica always on uses credit | `az containerapp update -n mrf-api-dev -g rg-mrf-a-dev --min-replicas 0` (only when no pipeline runs) |
