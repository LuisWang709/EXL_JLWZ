// Key Vault (RBAC mode) holding the app secrets (owner: A4). Values arrive as secure parameters at deploy time.
param location string
param env string
param appPrincipalId string
@description('Your own Entra object id - lets you read/rotate secrets. az ad signed-in-user show --query id -o tsv')
param adminObjectId string
@secure()
param apiKey string
@secure()
param llmApiKey string
@description('True when llmApiKey is set (kept separate so no output depends on the secret).')
param storeLlmKey bool

var suffix = take(uniqueString(resourceGroup().id), 6)
var kvReaderRole = '4633458b-17de-408a-b874-0445c86b69e6' // built-in role: Key Vault Secrets User
var kvOfficerRole = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' // built-in role: Key Vault Secrets Officer

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-mrf-${env}-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource apiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'mrf-api-key'
  properties: { value: apiKey }
}

resource llmKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (storeLlmKey) {
  parent: kv
  name: 'llm-api-key'
  properties: { value: llmApiKey }
}

resource appRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, appPrincipalId, kvReaderRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvReaderRole)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource adminManage 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminObjectId)) {
  scope: kv
  name: guid(kv.id, adminObjectId, kvOfficerRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvOfficerRole)
    principalId: adminObjectId
    principalType: 'User'
  }
}

output vaultUri string = kv.properties.vaultUri
output vaultName string = kv.name
output apiKeySecretUri string = '${kv.properties.vaultUri}secrets/mrf-api-key'
output llmKeySecretUri string = storeLlmKey ? '${kv.properties.vaultUri}secrets/llm-api-key' : ''
