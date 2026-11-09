// One environment (dev or demo) of the Model Risk Factory (owner: A4).
// The full sequence (shared -> image -> environment) is in infra/README.md.
targetScope = 'resourceGroup'

@allowed([ 'dev', 'demo' ])
param env string
param location string = resourceGroup().location

@description('Resource group of infra/shared.bicep (ACR + GitHub identity).')
param sharedResourceGroup string = 'rg-mrf-a-shared'
param acrName string
param apiImage string
param uiImage string = ''
param deployUi bool = false

@description('Principal id of id-mrf-github (shared.bicep output); gets Contributor here so CD can update apps.')
param githubPrincipalId string = ''
param adminObjectId string = ''

@description('Cosmos account from shared.bicep; empty = SQLite on local disk (data lost on restart).')
param cosmosAccountName string = ''

@description('Existing Azure OpenAI resource (created in the portal); used when llmProvider = azure_openai.')
param aoaiName string = ''
param aoaiResourceGroup string = sharedResourceGroup
param aoaiApiVersion string = '2025-04-01-preview'

@secure()
param apiKey string
@secure()
param llmApiKey string = ''
@allowed([ 'mock', 'openai', 'azure_openai', 'github_models' ])
param llmProvider string = 'azure_openai'
@description('Model name, or the Azure deployment name (name deployments after the model, e.g. gpt-5-mini).')
param llmModel string = 'gpt-5-mini'
param llmBaseUrl string = ''
@description('Env var that carries llmApiKey: OPENAI_API_KEY (openai / DeepSeek), AZURE_OPENAI_API_KEY, GITHUB_TOKEN.')
param llmKeyEnvName string = 'OPENAI_API_KEY'

@minValue(0)
@maxValue(1)
param apiMinReplicas int = 1
@minValue(0)
@maxValue(1)
param uiMinReplicas int = 0
@description('UTC. The timer only knocks; each model\'s Schedule.cron decides what is due.')
param monitorCron string = '0 * * * *'

var contributor = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

resource appId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mrf-app-${env}'
  location: location
}

module mon 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { location: location, env: env }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: { location: location, env: env, appPrincipalId: appId.properties.principalId }
}

module kv 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    env: env
    appPrincipalId: appId.properties.principalId
    adminObjectId: adminObjectId
    apiKey: apiKey
    llmApiKey: llmApiKey
    storeLlmKey: !empty(llmApiKey)
  }
}

module acrPull 'modules/acr-pull.bicep' = {
  name: 'acr-pull-${env}'
  scope: resourceGroup(sharedResourceGroup)
  params: { acrName: acrName, principalId: appId.properties.principalId }
}

module cosmosDb 'modules/cosmos-db.bicep' = if (!empty(cosmosAccountName)) {
  name: 'cosmos-db-${env}'
  scope: resourceGroup(sharedResourceGroup)
  params: { accountName: cosmosAccountName, databaseName: 'mrf-${env}', appPrincipalId: appId.properties.principalId }
}

module openaiAccess 'modules/openai-access.bicep' = if (llmProvider == 'azure_openai' && !empty(aoaiName)) {
  name: 'openai-access-${env}'
  scope: resourceGroup(aoaiResourceGroup)
  params: { accountName: aoaiName, principalId: appId.properties.principalId }
}

var storageEnv = empty(cosmosAccountName)
  ? []
  : [
      { name: 'MRF_STORAGE_BACKEND', value: 'cosmos' }
      { name: 'MRF_COSMOS_ENDPOINT', value: cosmosDb.?outputs.endpoint ?? '' }
      { name: 'MRF_COSMOS_DATABASE', value: 'mrf-${env}' }
    ]

var aoaiEnv = llmProvider == 'azure_openai'
  ? [
      { name: 'AZURE_OPENAI_ENDPOINT', value: openaiAccess.?outputs.endpoint ?? '' }
      { name: 'AZURE_OPENAI_API_VERSION', value: aoaiApiVersion }
    ]
  : []

module aca 'modules/aca.bicep' = {
  name: 'container-apps'
  params: {
    location: location
    env: env
    workspaceName: mon.outputs.workspaceName
    appInsightsName: mon.outputs.appInsightsName
    storageAccountName: storage.outputs.accountName
    shareName: storage.outputs.shareName
    identityId: appId.id
    identityClientId: appId.properties.clientId
    acrLoginServer: acrPull.outputs.loginServer // also orders the app after its AcrPull role
    apiImage: apiImage
    uiImage: uiImage
    deployUi: deployUi
    apiKeySecretUri: kv.outputs.apiKeySecretUri
    llmKeySecretUri: kv.outputs.llmKeySecretUri
    llmProvider: llmProvider
    llmModel: llmModel
    llmBaseUrl: llmProvider == 'openai' ? llmBaseUrl : ''
    llmKeyEnvName: llmKeyEnvName
    apiMinReplicas: apiMinReplicas
    uiMinReplicas: uiMinReplicas
    monitorCron: monitorCron
    extraEnv: concat(storageEnv, aoaiEnv)
  }
}

resource githubDeploy 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(githubPrincipalId)) {
  name: guid(resourceGroup().id, githubPrincipalId, contributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributor)
    principalId: githubPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output apiUrl string = 'https://${aca.outputs.apiFqdn}'
output uiUrl string = deployUi ? 'https://${aca.outputs.uiFqdn}' : ''
output keyVaultName string = kv.outputs.vaultName
