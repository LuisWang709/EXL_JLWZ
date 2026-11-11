// Shared resources used by both dev and demo (owner: A4). Deploy once into rg-mrf-a-shared:
//   az deployment group create -g rg-mrf-a-shared -f infra/shared.bicep
// Holds what must outlive "delete dev after 11/13": the image registry and the GitHub deploy identity.
targetScope = 'resourceGroup'

@description('Azure for Students only allows a few regions; ours is swedencentral.')
param location string = resourceGroup().location

// GitHub's immutable OIDC subject (repos created after 2026-07-15): owner@ownerId/repo@repoId.
// The ids never change, even if the repo is renamed. Old format 'LuisWang709/EXL_JLWZ' is rejected (AADSTS700213).
@description('GitHub repository that may deploy, as it appears in the OIDC subject.')
param githubRepo string = 'LuisWang709@304986476/EXL_JLWZ@1442945666'

@description('Cosmos DB free tier (one per subscription) holding one database per environment.')
param deployCosmos bool = true

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

// Free tier: the first 1000 RU/s and 25 GB are free. dev and demo each get a 400 RU/s shared-throughput
// database (infra/modules/cosmos-db.bicep), 800 RU/s in total, so the account stays free.
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = if (deployCosmos) {
  name: 'cosmos-mrf-a-${suffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0, isZoneRedundant: false } ]
    minimalTlsVersion: 'Tls12'
  }
}

output acrName string = acr.name
output cosmosAccountName string = deployCosmos ? cosmos.name : ''
output acrLoginServer string = acr.properties.loginServer
output githubClientId string = github.properties.clientId
output githubPrincipalId string = github.properties.principalId
