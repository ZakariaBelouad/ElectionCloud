# ElectionCloud team plan

Four teammates work from separate clones of one private Git repository. Zakaria works from the current project PC. Zelmati, Mesbah, and Benachour each use their own PC and clone. The target service placement comes from the project fiche. The current code already has a web app, Kafka worker, local Docker Compose demo, Cosmos DB backend tested against an emulator, and an Azure deployment script. Treat these as the starting point.

| Owner | Responsibility | Branch | Main files or directories |
| --- | --- | --- | --- |
| Zakaria Belouad (Person 1) | Azure application, storage, identity, dashboard, and deployment | `team/azure-app` | `web.py`, `cosmos_store.py`, `deploy-azure.ps1`, `AZURE.md` |
| Mohammed Reda Zelmati (Person 2) | AWS EC2 Kafka and separate EC2 tally host | `team/aws-kafka-tally` | `infra/aws/` |
| Saad Mesbah (Person 3) | Google Compute Engine standby and Google Cloud Functions | `team/gcp-recovery` | `infra/gcp/` |
| Oussama Benachour (Person 4) | AWS Lambda alerts, monitoring integration, Git workflow and end-to-end QA | `team/ops-integration` | `infra/ops/`, `.github/workflows/`, `tests/integration/` |

Person 1 owns shared application changes. Person 2 proposes changes to tally interfaces, Person 3 proposes changes to recovery interfaces, and Person 4 reviews interface changes and owns the integration checklist. Coordinate before editing shared files such as the Dockerfile, Compose configuration, requirements, or core voting code.

## Architecture to preserve

- **Azure PaaS.** App Service hosts the voting UI and API. Container Apps runs the Kafka consumer. Cosmos DB holds voter and election data and encrypted ballots in distinct logical records. Entra ID handles staff access, Application Gateway with WAF protects the hosted web edge, Key Vault holds deployment secrets, and Azure Monitor covers the Azure services.
- **AWS IaaS and FaaS.** A dedicated EC2 VM hosts Apache Kafka. A separate EC2 VM runs the post-close tally. Lambda handles technical alerts and administrator notifications, with CloudWatch for AWS monitoring.
- **Google Cloud IaaS and FaaS.** Compute Engine provides standby tally capacity. Google Cloud Functions provides supplemental checks and fallback notifications. Google Cloud Monitoring covers the Google Cloud services.
- **Ballot flow.** The Azure app queues encrypted ballots. The existing durable outbox is relayed through Kafka by the Container Apps worker, which also consumes and stores ballots. The fiche assigns the producer to App Service. Person 1 owns moving the relay/producer to the App Service side while preserving outbox recovery. Person 2 owns Kafka broker configuration and validates the producer/consumer contract. Keep the consumer in Container Apps.
- **Election rules.** One vote per verified voter, no voter identity or session token in Kafka, acceptance only after durable ballot storage, turnout during voting, and results only after closure. Local SQLite and the Cosmos emulator remain usable for development. A single Kafka broker is sufficient for the class demo.

## Day one on four separate machines

1. Zakaria makes the first push to the existing repository from this PC, then invites Zelmati, Mesbah, and Benachour. Include application source, Docker files, requirements, scripts, documentation, and these briefs. Add a `.gitignore` before staging. Exclude `*.db`, `*.db-*`, `*.pem`, `*.key`, real `.env` files, credentials, logs, and `__pycache__/`. Placeholder config can be tracked. Inspect the staged file list before the first push.
2. Everyone installs Git, Python, and Docker Desktop or Docker Engine with Compose. Each person clones the same URL, opens the clone in Codex, and pastes the contents of their assigned brief. Run the existing local demo using the README. Each machine uses its own Docker volumes and synthetic test election.
3. Branch from `main` with the assigned branch name. Push your own branch and open a pull request. Require a teammate review and passing CI before merging. Sync from `main` before integration. Share commits and reproducible setup instructions in Git. Share cloud access through individual identities and secrets through the cloud secret stores.
4. Person 4 records the exact tested commit and image tag. Deploy that revision to one shared demo environment after the team has authorized the resources and agreed on cleanup.

## Handoffs and integration order

- **First, agree on interfaces.** Person 1 publishes the environment-variable names and health event fields. Person 2 confirms the Kafka topic and auth contract and drafts the tally result schema with Person 1. Person 3 uses that same tally schema. Person 4 records the contracts and builds alert fixtures.
- **Then work in parallel.** Person 1 uses Docker Kafka and a Cosmos emulator. Person 2 uses synthetic election fixtures and a test Kafka client. Person 3 runs the same tally command against synthetic fixtures, with no dependency on a live incident. Person 4 builds CI and alert simulations.
- **Join the cloud pieces.** Person 2 hands Person 1 a private broker DNS name and port, TLS trust requirements, and Kafka ACL scope. Person 1 hands Persons 2 and 3 the Cosmos endpoint, election ID, and operator access requirements. Person 3 hands Person 4 the fallback invocation contract. Transfer credentials through secret stores.
- **Rehearse once together.** Issue and cast a synthetic ballot, verify durable receipt and replay handling, show turnout before close, close the election, run the AWS tally and show results, simulate a technical alert, then rehearse the Google Cloud standby tally and fallback notification. Confirm only one tally is published during failover. Capture version, logs, and expected versus actual results without exposing tokens or keys.

For Cloud deployment, one teammate should own each cloud account or resource group. All four should use separate Git identities and individual cloud access. A successful local test and a verified hosted deployment are separate milestones.

## Separate-PC operating instructions

**Zakaria seeds the existing repo once.** Use a new, empty folder outside the working demo. Copy and stage reviewed source by name: `electioncloud.py`, `web.py`, `kafka_worker.py`, `cosmos_store.py`, `Dockerfile`, `.dockerignore`, `compose.yaml`, all three requirements files, `deploy-azure.ps1`, `start-kafka.ps1`, `README.md`, `AZURE.md`, `TEAM-PLAN.md`, and `team-briefs/`. Add the ignore rules above and check `git diff --cached --name-only`. Confirm the existing repository is private, then push the reviewed baseline to `main`, then share the clone URL with the team.

**Every teammate runs these commands on their own PC.** The examples use PowerShell. Substitute your assigned branch and use your own Git identity and GitHub credentials.

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git ElectionCloud
cd ElectionCloud
git switch -c <assigned-branch>
docker version
docker compose version
docker compose -p ec-local build web worker
docker compose -p ec-local run --rm --no-deps admin init --private-key /keys/tally.pem "Candidate A" "Candidate B"
docker compose -p ec-local up -d --wait
```

Open http://127.0.0.1:8767 **on that same PC**. Everyone can use the same port because each PC has its own network and Docker daemon. Run `init` once for that project's volumes. Use `docker compose -p ec-local logs worker` to inspect ingestion and `docker compose -p ec-local down` when finished. To repeat from an empty election, use a new Compose project name. If both demos run on the same PC, set a different `ELECTIONCLOUD_PORT` first.

**Each PC owns its own runtime state.** A teammate's localhost URL, Docker volumes, SQLite file, emulator partition, and session token belong to their machine and election. Never use them as an integration dependency. Share code, sample configuration, fixtures, and test commands through Git. If a teammate uses a cloud sandbox before integration, use a unique election ID and resource names. In the shared demo environment, use one agreed election ID, the shared Cosmos container, and the same broker and release tag. Each teammate signs in individually. Exchange secret references through the cloud secret stores and access grants through cloud identities.

**Daily Git flow.** Start by fetching and merging current `origin/main` into your own branch. Stage only your task files. Push your branch, open a PR, and ask the teammate who consumes your interface to review it. Include the commit SHA, commands run, expected and observed outcomes, and remaining cloud-dependent checks. Never include screenshots with session tokens, keys, or cloud secrets.

**Suggested merge gates**

1. Zakaria pushes the clean baseline. Benachour adds the CI skeleton in a pull request. The four teammates agree on the Kafka, tally and alert contracts before their implementation PRs.
2. Each owner submits a locally runnable PR. Person 1 reviews any changes to shared Python files, Person 2 reviews Kafka and tally interoperability, Person 3 reviews failover steps, and Person 4 reviews testability and release evidence.
3. Person 4 selects the merged commit and release tag. Persons 1–3 deploy their assigned components from that revision after cloud access and resource authorization are available. Do one coordinated rehearsal against the shared cloud election.

## First handoff from Zakaria's PC

Zakaria has the current working source. He prepares the baseline from the allowlist and makes the first push to his existing repository from this PC. He then invites Zelmati, Mesbah, and Benachour and shares the clone URL. Benachour reviews the baseline and proposes CI and branch protection after receiving access. Zakaria applies repository settings that require owner access. After the baseline is pushed, all four open a clone of that same repository and work on their assigned branch. Zakaria can keep the existing local demo folder as a separate working copy.
### Zakaria's first push

Use the existing [ElectionCloud repository](https://github.com/ZakariaBelouad/ElectionCloud). Confirm its visibility is **Private** before pushing the baseline. In the clean staging copy described above, add the ignore rules and reviewed source first. Then run:

```powershell
git init -b main
git add .
git status --short
git diff --cached --name-only
```

Check the staged list for databases, keys, credentials, and real environment files. Once reviewed, run:

```powershell
git commit -m "Add ElectionCloud baseline"
git remote add origin https://github.com/ZakariaBelouad/ElectionCloud.git
git push -u origin main
```

Invite all three teammates after the first push. On this PC, create `team/azure-app` from the pushed baseline. Each teammate clones the same URL and creates their own branch from `main`.