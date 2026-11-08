// dev environment. Secrets and ids come from environment variables, never from this file:
//   MRF_API_KEY, LLM_API_KEY, ADMIN_OBJECT_ID, ACR_NAME, GITHUB_PRINCIPAL_ID, API_IMAGE (see infra/README.md)
using '../main.bicep'

param env = 'dev'
param acrName = readEnvironmentVariable('ACR_NAME')
param apiImage = readEnvironmentVariable('API_IMAGE')
param uiImage = readEnvironmentVariable('UI_IMAGE', '')
param deployUi = !empty(readEnvironmentVariable('UI_IMAGE', ''))
param githubPrincipalId = readEnvironmentVariable('GITHUB_PRINCIPAL_ID', '')
param adminObjectId = readEnvironmentVariable('ADMIN_OBJECT_ID', '')

param apiKey = readEnvironmentVariable('MRF_API_KEY')
param llmApiKey = readEnvironmentVariable('LLM_API_KEY', '')
param llmProvider = readEnvironmentVariable('LLM_PROVIDER', 'openai')
param llmModel = readEnvironmentVariable('LLM_MODEL', 'deepseek-chat')
param llmBaseUrl = readEnvironmentVariable('LLM_BASE_URL', 'https://api.deepseek.com')

// dev: scale to 0 by hand at night (az containerapp update --min-replicas 0) when no pipeline runs
param apiMinReplicas = 1
param uiMinReplicas = 0
