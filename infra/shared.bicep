// Shared resources used by both dev and demo (owner: A4). Deploy once into rg-mrf-a-shared:
//   az deployment group create -g rg-mrf-a-shared -f infra/shared.bicep
// Holds what must outlive "delete dev after 11/13": the image registry and the GitHub deploy identity.
targetScope = 'resourceGroup'

@description('Azure for Students only allows a few regions; ours is swedencentral.')
param location string = resourceGroup().location

@description('GitHub repository that may deploy (OIDC subject).')
param githubRepo string = 'LuisWang709/EXL_JLWZ'

var suffix = take(uniqueString(resourceGroup().id), 8)
var acrPushRole = '8311e382-0749-4cb8-b61a-304f252e45ec'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrmrfa${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// GitHub Actions logs in with this identity through OIDC - no secret stored anywhere.
resource github 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mrf-github'
  location: location
}

resource githubMain 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: github
  name: 'gh-main'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepo}:ref:refs/heads/main'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

resource githubAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, github.id, acrPushRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRole)
    principalId: github.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output githubClientId string = github.properties.clientId
output githubPrincipalId string = github.properties.principalId
