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

# first image
az acr build -r "$ACR_NAME" -t mrf-api:bootstrap -f docker/Dockerfile.api .
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
| `/readyz` says `llm_config: missing AZURE_OPENAI_ENDPOINT` | `AOAI_NAME` was empty at deploy time | export it and redeploy |
| LLM calls fail with 401/403 | the "Cognitive Services OpenAI User" role is not effective yet | wait 5 minutes |
| LLM calls fail with `Unsupported parameter/value` | deployment name does not start with the model name | set `MRF_LLM_REASONING=true` on the app, or rename the deployment |
| `Cosmos container ... does not exist` | `COSMOS_ACCOUNT` was empty at deploy time, or a new collection was added | redeploy; new collections must be added to `modules/cosmos-db.bicep` |
| Cosmos free tier error on `shared.bicep` | the subscription already has a free-tier account | deploy with `-p deployCosmos=false` and tell A4 |
| logs | - | `az containerapp logs show -n mrf-api-dev -g rg-mrf-a-dev --follow` |
| save money at night (dev) | one replica always on uses credit | `az containerapp update -n mrf-api-dev -g rg-mrf-a-dev --min-replicas 0` (only when no pipeline runs) |
