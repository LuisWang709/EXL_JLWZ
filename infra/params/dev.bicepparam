// dev environment. Secrets and ids come from environment variables, never from this file:
//   ACR_NAME, API_IMAGE, MRF_API_KEY, COSMOS_ACCOUNT, AOAI_NAME, GITHUB_PRINCIPAL_ID, ADMIN_OBJECT_ID (infra/README.md)
using '../main.bicep'

param env = 'dev'
param acrName = readEnvironmentVariable('ACR_NAME')
param apiImage = readEnvironmentVariable('API_IMAGE')
param uiImage = readEnvironmentVariable('UI_IMAGE', '')
param deployUi = !empty(readEnvironmentVariable('UI_IMAGE', ''))
param githubPrincipalId = readEnvironmentVariable('GITHUB_PRINCIPAL_ID', '')
param adminObjectId = readEnvironmentVariable('ADMIN_OBJECT_ID', '')

param cosmosAccountName = readEnvironmentVariable('COSMOS_ACCOUNT', '')
param aoaiName = readEnvironmentVariable('AOAI_NAME', '')
param aoaiResourceGroup = readEnvironmentVariable('AOAI_RESOURCE_GROUP', 'rg-mrf-a-shared')

param apiKey = readEnvironmentVariable('MRF_API_KEY')
param llmApiKey = readEnvironmentVariable('LLM_API_KEY', '')
param llmProvider = readEnvironmentVariable('LLM_PROVIDER', 'azure_openai')
param llmModel = readEnvironmentVariable('LLM_MODEL', 'gpt-5-mini')
param llmBaseUrl = readEnvironmentVariable('LLM_BASE_URL', '')
param llmKeyEnvName = readEnvironmentVariable('LLM_KEY_ENV', 'OPENAI_API_KEY')

// dev: scale to 0 by hand at night (az containerapp update --min-replicas 0) when no pipeline runs.
// UI stays warm too: at 0 the first visitor waits 10-30 s for a cold start before the sign-in page appears.
param apiMinReplicas = 1
param uiMinReplicas = 1
