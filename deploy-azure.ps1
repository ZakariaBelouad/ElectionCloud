param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$Registry,
    [Parameter(Mandatory)][string]$WebApp,
    [Parameter(Mandatory)][string]$WorkerApp,
    [Parameter(Mandatory)][string]$CosmosAccount,
    [Parameter(Mandatory)][string]$CosmosDatabase,
    [Parameter(Mandatory)][string]$CosmosContainer,
    [Parameter(Mandatory)][string]$ElectionId,
    [Parameter(Mandatory)][string]$KafkaBroker,
    [Parameter(Mandatory)][ValidatePattern('^https://[a-z0-9-]+\.vault\.azure\.net/secrets/[a-zA-Z0-9-]+(?:/[a-fA-F0-9]+)?/?$')][string]$PublisherUsernameSecretUri,
    [Parameter(Mandatory)][ValidatePattern('^https://[a-z0-9-]+\.vault\.azure\.net/secrets/[a-zA-Z0-9-]+(?:/[a-fA-F0-9]+)?/?$')][string]$PublisherPasswordSecretUri,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')][string]$Tag
)

$ErrorActionPreference = 'Stop'

function Invoke-Azure {
    & az @args --subscription $SubscriptionId --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed during '$($args[0..1] -join ' ')'." }
}

function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker failed during '$($args[0..1] -join ' ')'." }
}

Get-Command az, docker -ErrorAction Stop | Out-Null
Invoke-Azure account show --query id --output none
$registryHost = Invoke-Azure acr show -g $ResourceGroup -n $Registry --query loginServer -o tsv
$cosmosEndpoint = Invoke-Azure cosmosdb show -g $ResourceGroup -n $CosmosAccount --query documentEndpoint -o tsv
$partition = Invoke-Azure cosmosdb sql container show -g $ResourceGroup -a $CosmosAccount -d $CosmosDatabase -n $CosmosContainer --query 'resource.partitionKey.paths[0]' -o tsv
if ($partition -ne '/electionId') { throw 'The Cosmos container must be partitioned by /electionId.' }

$site = Invoke-Azure webapp show -g $ResourceGroup -n $WebApp -o json | ConvertFrom-Json
$siteConfig = Invoke-Azure webapp config show -g $ResourceGroup -n $WebApp -o json | ConvertFrom-Json
$auth = Invoke-Azure webapp auth show -g $ResourceGroup -n $WebApp -o json | ConvertFrom-Json
if (!$site.httpsOnly -or !$auth.platform.enabled -or !$auth.globalValidation.requireAuthentication -or
    !$auth.identityProviders.azureActiveDirectory.enabled -or $auth.globalValidation.excludedPaths) {
    throw 'Enable HTTPS-only and required Microsoft Entra authentication with no excluded paths before deploying.'
}
if (!$siteConfig.acrUseManagedIdentityCreds -or $siteConfig.acrUserManagedIdentityID) {
    throw 'Configure the web app to pull images using its system-assigned managed identity.'
}
if ($siteConfig.appCommandLine) { throw 'Clear the App Service startup command so the container can start its publisher.' }

$worker = Invoke-Azure containerapp show -g $ResourceGroup -n $WorkerApp -o json | ConvertFrom-Json
if ($worker.properties.configuration.ingress) { throw 'Disable ingress on the Kafka worker before deploying.' }
if (!$site.identity.principalId -or !$worker.identity.principalId) {
    throw 'Enable a system-assigned managed identity on each app.'
}
$registryBinding = @($worker.properties.configuration.registries | Where-Object {
    $_.server -eq $registryHost -and $_.identity -eq 'system'
})
if ($registryBinding.Count -eq 0) { throw 'Configure the worker to use its system identity to pull from ACR.' }
$secretNames = @($worker.properties.configuration.secrets | ForEach-Object { $_.name })
if ('kafka-username' -notin $secretNames -or 'kafka-password' -notin $secretNames) {
    throw 'Configure kafka-username and kafka-password as Container Apps secrets before deploying.'
}

$webImage = "$registryHost/electioncloud-web:$Tag"
$workerImage = "$registryHost/electioncloud-worker:$Tag"
$storage = @(
    'ELECTIONCLOUD_STORAGE=cosmos'
    "ELECTIONCLOUD_ELECTION_ID=$ElectionId"
    'COSMOS_AUTH=managed-identity'
    "COSMOS_ENDPOINT=$cosmosEndpoint"
    "COSMOS_DATABASE=$CosmosDatabase"
    "COSMOS_CONTAINER=$CosmosContainer"
)
$kafka = @(
    'ELECTIONCLOUD_KAFKA_SECURITY_PROTOCOL=SASL_SSL'
    "ELECTIONCLOUD_BROKER=$KafkaBroker"
)

Invoke-Azure acr login --name $Registry -o none
Push-Location -LiteralPath $PSScriptRoot
try {
    Invoke-Docker buildx build --platform linux/amd64 --target azure-web --tag $webImage --push .
    Invoke-Docker buildx build --platform linux/amd64 --target worker --tag $workerImage --push .
}
finally {
    Pop-Location
}

# Use the hosted app's actual hostname, including Azure-generated suffixes.
Invoke-Azure webapp config appsettings set -g $ResourceGroup -n $WebApp --settings @storage @kafka `
    "ELECTIONCLOUD_KAFKA_USERNAME=@Microsoft.KeyVault(SecretUri=$PublisherUsernameSecretUri)" `
    "ELECTIONCLOUD_KAFKA_PASSWORD=@Microsoft.KeyVault(SecretUri=$PublisherPasswordSecretUri)" `
    "ELECTIONCLOUD_PUBLIC_HOST=$($site.defaultHostName)" 'WEBSITES_PORT=8767' `
    'WEBSITE_WARMUP_PATH=/healthz' 'WEBSITE_WARMUP_STATUSES=200' -o none
Invoke-Azure webapp config container set -g $ResourceGroup -n $WebApp `
    --container-image-name $webImage --container-registry-url "https://$registryHost" -o none

Invoke-Azure containerapp update -g $ResourceGroup -n $WorkerApp --image $workerImage `
    --command python --args kafka_worker.py --min-replicas 1 --max-replicas 1 `
    --set-env-vars @storage @kafka `
    'ELECTIONCLOUD_KAFKA_ROLE=consumer' `
    'ELECTIONCLOUD_KAFKA_USERNAME=secretref:kafka-username' `
    'ELECTIONCLOUD_KAFKA_PASSWORD=secretref:kafka-password' -o none

"Deployment submitted. Open https://$($site.defaultHostName)/ after the services are ready."
