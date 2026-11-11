// Lets the app identity call an existing Azure OpenAI resource with Entra ID (no key) (owner: A4).
// The resource and its model deployment are created in the portal (see the Azure tutorial).
param accountName string
param principalId string

var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // built-in role: Cognitive Services OpenAI User

resource aoai 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: accountName
}

resource user 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aoai
  name: guid(aoai.id, principalId, openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUser)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = aoai.properties.endpoint
