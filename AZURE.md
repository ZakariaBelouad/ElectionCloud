# Deploy ElectionCloud to Azure

This deployment uses a Linux App Service web app, an Azure Container Apps worker, Azure Container Registry, and Cosmos DB for NoSQL. It connects to an existing Kafka broker on AWS EC2. Use a dedicated academic demo environment and synthetic voters.

## Prepare the resources

1. Create a resource group, an Azure Container Registry using **RBAC Registry Permissions**, a Cosmos DB for NoSQL account, and a database and container with partition key `/electionId`. The deployment script expects these resources and the two apps below in the same resource group.
2. Create a **Linux Web App for Containers** in App Service using a single instance and the classic custom-container configuration. Enable **HTTPS Only** and a system-assigned identity. In **Authentication**, add Microsoft Entra ID and require sign-in for all application requests. In the enterprise application, require assignment and assign only the demo operators. Both voting forms are available to signed-in demo operators.
3. Create an Azure Container Apps environment with network access to the Kafka broker, then create a single-container worker app with ingress disabled, single-revision mode, and a system-assigned identity. Use a placeholder image when creating the apps. The deployment script replaces both images.
4. Grant both service identities **AcrPull** on the registry and configure each service to pull from ACR using its system-assigned identity. Enable ARM-audience authentication in ACR. Grant the deployment operator permission to push images.
5. Grant both service identities and the initialization operator **Cosmos DB Built-in Data Contributor** on the demo container using **Cosmos DB data-plane role assignments**. Ensure the apps and the initialization workstation can reach the account endpoint.
6. Provide a Kafka broker whose advertised address resolves and is reachable over a private route from both App Service and the Container Apps environment. Integrate App Service with a VNet that can reach that route. Use TLS trusted by both images. Create separate `SCRAM-SHA-512` principals. The publisher needs create, describe, and write access under the `electioncloud-` topic prefix, plus idempotent production. The consumer needs describe and read access and access to the corresponding consumer group. Store the publisher credentials in Key Vault, and grant the App Service system identity permission to read them. Configure `kafka-username` and `kafka-password` for the consumer as Container Apps secrets.

The `azure-web` image starts the HTTP app and an independent Kafka publisher in the App Service container. Leave the App Service startup-command override blank. If the publisher exits, it is restarted after five seconds and queued ballots remain in Cosmos DB. The Container Apps revision runs the worker in consumer-only mode. The App Service health endpoint checks the HTTP process. Verify publisher readiness and consumer readiness separately in their logs.

See [App Service Key Vault references](https://learn.microsoft.com/azure/app-service/app-service-key-vault-references) and [App Service VNet integration](https://learn.microsoft.com/azure/app-service/overview-vnet-integration).

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
  -ElectionId "azure-demo-001" -KafkaBroker "<private-kafka-host>:9094" `
  -PublisherUsernameSecretUri "https://<vault>.vault.azure.net/secrets/kafka-publisher-username" `
  -PublisherPasswordSecretUri "https://<vault>.vault.azure.net/secrets/kafka-publisher-password" `
  -Tag "demo-001"
```

Check that the web URL requires sign-in, App Service logs show that the publisher is ready, and the worker logs show it listening on the same topic. Cast a synthetic ballot and verify that a receipt appears after storage. Verify turnout, then close and count it from the same operator PowerShell session:

```powershell
az containerapp logs show -g "<resource-group>" -n "<worker-app-name>" --tail 30
python electioncloud.py close
python electioncloud.py tally --private-key azure-demo-tally.pem
```

The script updates existing Azure resources. Resource provisioning, private connectivity to EC2, and the project brief's alerting and recovery services are separate deployment work.
