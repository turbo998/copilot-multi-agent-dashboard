// Agent Dashboard infrastructure
// Resources: Storage Account + Container Registry + Log Analytics + Container Apps Env + Container App
// Auth: Managed Identity (system-assigned on the Container App) -> Storage Blob Data Reader
// NOTE: Easy Auth (Entra ID) is configured POST-DEPLOY via az CLI (see scripts/configure-easyauth.sh)
//       because Bicep auth config requires an existing app registration.

@description('Resource prefix (lowercase, alphanumeric only, max 14 chars)')
@maxLength(14)
param prefix string = 'agentdash'

@description('Region')
param location string = resourceGroup().location

@description('Existing ACR name (must already contain the containerImage)')
param acrName string

@description('Container image (full path including tag), e.g. agentdashacr.azurecr.io/dashboard:v1')
param containerImage string

@description('Min replicas (1 to avoid cold start)')
param minReplicas int = 1

@description('Max replicas')
param maxReplicas int = 2

@description('Container CPU cores')
param cpu string = '0.5'

@description('Container memory')
param memory string = '1Gi'

var uniq = uniqueString(resourceGroup().id, prefix)
var storageName = toLower('st${prefix}${take(uniq, 6)}')
var lawName = '${prefix}-law'
var envName = '${prefix}-env'
var appName = '${prefix}-app'
var containerName = 'agent-sessions'

// ---------------- Storage ----------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

// ---------------- ACR (existing) ----------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

// ---------------- Log Analytics ----------------
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------------- Container Apps Environment ----------------
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
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

// ---------------- Container App ----------------
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.name
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'dashboard'
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            { name: 'AGENTDASH_BLOB_URL', value: 'https://${storage.name}.blob.${environment().suffixes.storage}' }
            { name: 'AGENTDASH_BLOB_CONTAINER', value: containerName }
            { name: 'AGENTDASH_HERMES_DB', value: '/tmp/snap/hermes.db' }
            { name: 'AGENTDASH_GHCP_DB', value: '/tmp/snap/ghcp.db' }
            { name: 'AGENTDASH_OPENCLAW_DIR', value: '/tmp/snap/openclaw' }
            { name: 'AGENTDASH_REFRESH_INTERVAL', value: '300' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

// ---------------- RBAC: grant the App's MI Storage Blob Data Reader on the container ----------------
var blobReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1' // Storage Blob Data Reader

resource blobReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, blobReaderRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobReaderRoleId)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------- Outputs ----------------
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output appName string = app.name
output appPrincipalId string = app.identity.principalId
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output storageName string = storage.name
output storageContainer string = containerName
