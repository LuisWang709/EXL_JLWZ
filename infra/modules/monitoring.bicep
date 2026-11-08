// Log Analytics + workspace-based Application Insights (owner: A4).
param location string
param env string

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-mrf-${env}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-mrf-${env}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

output workspaceName string = law.name
output appInsightsName string = appi.name
