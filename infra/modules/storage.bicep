// Storage: Azure Files share mounted at /data (reports, blobs, mlruns) + a blob container for later (owner: A4).
// SQLite files do NOT go here - WAL mode does not work on network file systems; they live in /state (EmptyDir).
param location string
param env string
param appPrincipalId string

var suffix = take(uniqueString(resourceGroup().id), 8)
var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stmrf${env}${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: sa
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: files
  name: 'data'
  properties: { shareQuota: 10 }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
}

resource reports 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'mrf'
}

resource appBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, appPrincipalId, blobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output accountName string = sa.name
output shareName string = share.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
