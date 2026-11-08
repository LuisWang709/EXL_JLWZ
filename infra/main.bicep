// One environment (dev or demo) of the Model Risk Factory (owner: A4).
//   export MRF_API_KEY=$(openssl rand -hex 24) LLM_API_KEY=<key from A1> ADMIN_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
//   az deployment group create -g rg-mrf-a-dev -f infra/main.bicep -p infra/params/dev.bicepparam
// See infra/README.md for the full first-time sequence.
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

@secure()
param apiKey string
@secure()
param llmApiKey string = ''
@allowed([ 'mock', 'openai', 'azure_openai', 'github_models' ])
param llmProvider string = 'openai'
param llmModel string = 'deepseek-chat'
param llmBaseUrl string = 'https://api.deepseek.com'
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
