// Container Apps environment, the API app (API + /mcp + workers), the optional UI app and the
// monitoring timer job (owner: A4).
param location string
param env string
param workspaceName string
param appInsightsName string
param storageAccountName string
param shareName string
param identityId string
param identityClientId string
param acrLoginServer string
param apiImage string
param uiImage string
param deployUi bool
param apiKeySecretUri string
param llmKeySecretUri string
param llmProvider string
param llmModel string
param llmBaseUrl string
param llmKeyEnvName string
param apiMinReplicas int
param uiMinReplicas int
param monitorCron string
@description('Extra API env vars from main.bicep (Cosmos, Azure OpenAI endpoint ...).')
param extraEnv array = []

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource appi 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-mrf-${env}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource dataStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: acaEnv
  name: 'mrfdata'
  properties: {
    azureFile: {
      accountName: sa.name
      accountKey: sa.listKeys().keys[0].value
      shareName: shareName
      accessMode: 'ReadWrite'
    }
  }
}

var secrets = concat(
  [ { name: 'api-key', keyVaultUrl: apiKeySecretUri, identity: identityId } ],
  empty(llmKeySecretUri) ? [] : [ { name: 'llm-api-key', keyVaultUrl: llmKeySecretUri, identity: identityId } ]
)

var llmEnv = concat(
  [
    { name: 'MRF_LLM_PROVIDER', value: llmProvider }
    { name: 'MRF_LLM_MODEL', value: llmModel }
  ],
  empty(llmBaseUrl) ? [] : [ { name: 'OPENAI_BASE_URL', value: llmBaseUrl } ],
  empty(llmKeySecretUri) ? [] : [ { name: llmKeyEnvName, secretRef: 'llm-api-key' } ]
)

var apiEnv = concat(
  [
    { name: 'MRF_ENV', value: env }
    { name: 'MRF_API_KEY', secretRef: 'api-key' }
    { name: 'AZURE_CLIENT_ID', value: identityClientId } // user-assigned identity: tell azure-identity which one
    { name: 'MRF_DATA_DIR', value: '/data' }
    { name: 'MRF_SQLITE_PATH', value: '/state/mrf.sqlite' }
    { name: 'MRF_CHECKPOINT_PATH', value: '/state/checkpoints.sqlite' }
    { name: 'MLFLOW_TRACKING_URI', value: '/data/mlruns' }
    { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
  ],
  llmEnv,
  extraEnv
)

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'mrf-api-${env}'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    environmentId: acaEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: apiEnv
          volumeMounts: [
            { volumeName: 'data', mountPath: '/data' }
            { volumeName: 'state', mountPath: '/state' }
          ]
          probes: [
            { type: 'Startup', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 5, failureThreshold: 24 }
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/readyz', port: 8000 }, periodSeconds: 15 }
          ]
        }
      ]
      // the job queue lives in-process: exactly one replica, never more
      scale: { minReplicas: apiMinReplicas, maxReplicas: 1 }
      volumes: [
        { name: 'data', storageType: 'AzureFile', storageName: dataStorage.name }
        { name: 'state', storageType: 'EmptyDir' }
      ]
    }
  }
}

resource ui 'Microsoft.App/containerApps@2024-03-01' = if (deployUi) {
  name: 'mrf-ui-${env}'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    environmentId: acaEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8501, transport: 'auto', stickySessions: { affinity: 'sticky' } }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: [ { name: 'api-key', keyVaultUrl: apiKeySecretUri, identity: identityId } ]
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: uiImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'API_BASE_URL', value: 'https://${api.properties.configuration.ingress.fqdn}' }
            { name: 'MRF_API_KEY', secretRef: 'api-key' }
          ]
        }
      ]
      scale: { minReplicas: uiMinReplicas, maxReplicas: 1 } // Streamlit keeps a websocket per session
    }
  }
}

// Timer: knocks on POST /api/v1/monitoring/runs; all computation happens inside the API process.
resource monitor 'Microsoft.App/jobs@2024-03-01' = {
  name: 'mrf-monitor-${env}'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    environmentId: acaEnv.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 300
      replicaRetryLimit: 1
      scheduleTriggerConfig: { cronExpression: monitorCron, parallelism: 1, replicaCompletionCount: 1 }
      secrets: [ { name: 'api-key', keyVaultUrl: apiKeySecretUri, identity: identityId } ]
    }
    template: {
      containers: [
        {
          name: 'tick'
          image: 'curlimages/curl:8.10.1'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'API_KEY', secretRef: 'api-key' }
            { name: 'API_URL', value: 'https://${api.properties.configuration.ingress.fqdn}' }
          ]
          command: [ 'sh', '-c', 'curl -fsS -X POST -H "X-API-Key: $API_KEY" "$API_URL/api/v1/monitoring/runs"' ]
        }
      ]
    }
  }
}

output apiFqdn string = api.properties.configuration.ingress.fqdn
output uiFqdn string = ui.?properties.configuration.ingress.fqdn ?? ''
