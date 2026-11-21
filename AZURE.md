# Deploy ElectionCloud to Azure

This deployment uses a Linux App Service web app, an Azure Container Apps worker, Azure Container Registry, and Cosmos DB for NoSQL. It connects to an existing Kafka broker on AWS EC2. Use a dedicated academic demo environment and synthetic voters.

## Prepare the resources

1. Create a resource group, an Azure Container Registry using **RBAC Registry Permissions**, a Cosmos DB for NoSQL account, and a database and container with partition key `/electionId`. The deployment script expects these resources and the two apps below in the same resource group.
2. Create a **Linux Web App for Containers** in App Service using a single instance and the classic custom-container configuration. Enable **HTTPS Only** and a system-assigned identity. In **Authentication**, add Microsoft Entra ID and require sign-in for all application requests. In the enterprise application, require assignment and assign only the demo operators. Both voting forms are available to signed-in demo operators.
3. Create an Azure Container Apps environment with network access to the Kafka broker, then create a single-container worker app with ingress disabled, single-revision mode, and a system-assigned identity. Use a placeholder image when creating the apps. The deployment script replaces both images.
4. Grant both service identities **AcrPull** on the registry and configure each service to pull from ACR using its system-assigned identity. Enable ARM-audience authentication in ACR. Grant the deployment operator permission to push images.
5. Grant both service identities and the initialization operator **Cosmos DB Built-in Data Contributor** on the demo container using **Cosmos DB data-plane role assignments**. Ensure the apps and the initialization workstation can reach the account endpoint.
6. Provide a Kafka broker whose advertised address is resolvable and reachable from the worker environment. Use a private cross-cloud route and a TLS certificate trusted by the worker image. Create a dedicated `SCRAM-SHA-512` Kafka principal. Grant it permissions to create, describe, write to, and read from the election topic under the `electioncloud-` prefix, read the corresponding consumer group, and use idempotent production. Configure `kafka-username` and `kafka-password` as Container Apps secrets. Key Vault references can supply their values.

Microsoft references for [App Service container setup](https://learn.microsoft.com/azure/app-service/configure-custom-container), [Entra sign-in](https://learn.microsoft.com/en-us/entra/identity-platform/multi-service-web-app-authentication-app-service), [Container Apps registry identity](https://learn.microsoft.com/en-us/cli/azure/containerapp/registry), and [Cosmos data-plane roles](https://learn.microsoft.com/en-us/cli/azure/cosmosdb/sql/role/assignment).

## Initialize the election

Install Azure CLI, open PowerShell in the ElectionCloud directory, and sign in with the operator account. Use your actual endpoint and resource names.

```powershell
az login
az account set --subscription "<subscription-id>"
python -m pip install -r requirements-cosmos.txt

$env:ELECTIONCLOUD_STORAGE = "cosmos"
$env:ELECTIONCLOUD_ELECTION_ID = "azure-demo-001"
$env:COSMOS_AUTH = "azure-cli"
$env:COSMOS_ENDPOINT = "https://<cosmos-account>.documents.azure.com:443/"
$env:COSMOS_DATABASE = "<database>"
$env:COSMOS_CONTAINER = "<container>"
python electioncloud.py init --private-key azure-demo-tally.pem "Candidate A" "Candidate B"
```

Keep the private tally key on the operator workstation in restricted storage. The containers only need the public key stored with the election.

## Publish and deploy

With Docker Desktop running, use a new tag for each release:

```powershell
.\deploy-azure.ps1 -SubscriptionId "<subscription-id>" -ResourceGroup "<resource-group>" `
  -Registry "<acr-name>" -WebApp "<web-app-name>" -WorkerApp "<worker-app-name>" `
  -CosmosAccount "<cosmos-account>" -CosmosDatabase "<database>" -CosmosContainer "<container>" `
  -ElectionId "azure-demo-001" -KafkaBroker "<private-kafka-host>:9094" -Tag "demo-001"
```

Check that the web URL requires sign-in, the worker logs show it listening on the election topic, and a synthetic ballot gets a receipt after storage. Verify turnout then close and count it from the same operator PowerShell session:

```powershell
az containerapp logs show -g "<resource-group>" -n "<worker-app-name>" --tail 30
python electioncloud.py close
python electioncloud.py tally --private-key azure-demo-tally.pem
```

The script updates existing Azure resources. Resource provisioning, private connectivity to EC2, and the project brief's alerting and recovery services are separate deployment work.
