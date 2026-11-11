// One environment's database on the shared free-tier Cosmos account, plus data-plane access for the app
// identity (owner: A4). Deployed into rg-mrf-a-shared through a module scope from main.bicep.
// Containers = mrf.storage.cosmos.REQUIRED_CONTAINERS (one per collection, partition key /id); with managed
// identity the app cannot create containers itself, so this list must follow A1's Collections.
param accountName string
param databaseName string
param appPrincipalId string
param throughput int = 400

var containers = [
  'alerts'
  'audit'
  'datasets'
  'documents'
  'idempotency'
  'jobs'
  'models'
  'monitoring_metrics'
  'pipelines'
  'quality_reports'
  'ratings'
  'rebuilds'
  'reports'
  'reviews'
  'runs'
  'schedules'
]

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: accountName
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: { id: databaseName }
    options: { throughput: throughput } // shared by every container below
  }
}

resource coll 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [
  for name in containers: {
    parent: db
    name: name
    properties: {
      resource: {
        id: name
        partitionKey: { paths: [ '/id' ], kind: 'Hash' }
      }
    }
  }
]

// Cosmos data-plane RBAC (not Azure RBAC): built-in "Cosmos DB Built-in Data Contributor", scoped to this database
resource dataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: account
  name: guid(account.id, databaseName, appPrincipalId)
  properties: {
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: appPrincipalId
    scope: '${account.id}/dbs/${databaseName}'
  }
}

output endpoint string = account.properties.documentEndpoint
