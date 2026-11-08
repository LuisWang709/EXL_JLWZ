# infra (owner: A4)

Bicep for Team A on Azure for Students (region **swedencentral**, the one our subscription allows).

| Resource group | File | Contents |
| --- | --- | --- |
| `rg-mrf-a-shared` | `shared.bicep` | ACR (Basic), `id-mrf-github` (GitHub OIDC identity, AcrPush) - survives deleting dev |
| `rg-mrf-a-dev` / `rg-mrf-a-demo` | `main.bicep` + `params/<env>.bicepparam` | Log Analytics + App Insights, storage (Azure Files `/data`), Key Vault, app identity, Container Apps env, `mrf-api-<env>`, optional `mrf-ui-<env>`, `mrf-monitor-<env>` timer job |

Design constraints (from A1's runtime):
- **`mrf-api` has exactly one replica** - the job queue runs in-process.
- SQLite + LangGraph checkpoints live on `/state` (EmptyDir, lost on restart). SQLite uses WAL, which does not
  work on network file systems, so they must not go on Azure Files. Do not redeploy while a pipeline runs;
  business data survives restarts once A1's Cosmos repository lands.
- `/data` (Azure Files): blobs, reports, `mlruns/`.
- LLM: DeepSeek through the OpenAI-compatible provider (`MRF_LLM_PROVIDER=openai`, `OPENAI_BASE_URL`,
  `OPENAI_API_KEY` from Key Vault). Switch with `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_KEY_ENV`.
- Secrets never live in files: Bicep receives them as secure parameters read from your shell environment and
  stores them in Key Vault; the apps read them through their managed identity.

## First deployment (run on your machine, as the subscription owner)

```bash
cd <repo root>
az login
az account set --subscription "<Azure for Students subscription name or id>"
az bicep install

# 1. shared resources (once)
az group create -n rg-mrf-a-shared -l swedencentral
az deployment group create -g rg-mrf-a-shared -f infra/shared.bicep -o none
export ACR_NAME=$(az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.acrName.value -o tsv)
export GITHUB_PRINCIPAL_ID=$(az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.githubPrincipalId.value -o tsv)

# 2. first API image (built in Azure, so amd64 even on an Apple-silicon Mac)
az acr build -r "$ACR_NAME" -t mrf-api:bootstrap -f docker/Dockerfile.api .
export API_IMAGE="$ACR_NAME.azurecr.io/mrf-api:bootstrap"

# 3. secrets - keep them in your password manager, never commit or paste them in chat
export MRF_API_KEY=$(openssl rand -hex 24)
export LLM_API_KEY='<DeepSeek key from A1>'
export ADMIN_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)   # optional: lets you read the vault

# 4. dev
az deployment group what-if -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam
az deployment group create  -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam -o none

# 5. check
API=$(az deployment group show -g rg-mrf-a-dev -n main --query properties.outputs.apiUrl.value -o tsv)
curl -s "$API/healthz"; echo; curl -s "$API/readyz"; echo
curl -s -H "X-API-Key: $MRF_API_KEY" "$API/api/v1/models"; echo
```

Demo is the same with `rg-mrf-a-demo` and `params/demo.bicepparam`, using its **own** `MRF_API_KEY`
(and `UI_IMAGE` once the UI exists, which turns `deployUi` on).

## GitHub settings for CD (repo Settings -> Secrets and variables -> Actions)

| Kind | Name | Value |
| --- | --- | --- |
| secret | `AZURE_CLIENT_ID` | `az deployment group show -g rg-mrf-a-shared -n shared --query properties.outputs.githubClientId.value -o tsv` |
| secret | `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| secret | `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| secret | `MRF_DEV_API_KEY` / `MRF_DEMO_API_KEY` | the `MRF_API_KEY` you used for that environment |
| variable | `ACR_NAME` | `echo $ACR_NAME` |

Then `cd-dev.yml` deploys every green `main`; `cd-demo.yml` is run by hand with a tag.

## When things go wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| `RequestDisallowedByAzure` | region outside the student policy | keep everything in swedencentral |
| app creation fails pulling the image (`UNAUTHORIZED`) | the AcrPull role was not effective yet | wait 2-3 minutes, run the same `az deployment group create` again |
| Key Vault name conflict after deleting a group | soft-deleted vault still reserved (7 days) | `az keyvault purge -n <name>` |
| `/readyz` says `data_dir: error` | the Azure Files mount is not writable for uid 10001 | tell A4; workaround: point `MRF_DATA_DIR` to `/state` (not persistent) |
| `/readyz` says `llm_config: missing OPENAI_API_KEY` | `LLM_API_KEY` was empty at deploy time | export it and redeploy |
| logs | - | `az containerapp logs show -n mrf-api-dev -g rg-mrf-a-dev --follow` |
| save money at night (dev) | one replica always on uses credit | `az containerapp update -n mrf-api-dev -g rg-mrf-a-dev --min-replicas 0` (only when no pipeline runs) |
