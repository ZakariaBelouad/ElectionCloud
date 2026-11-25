# Deployment inventory

Built from the architecture section of `TEAM-PLAN.md` and what exists in the repository on 2026-11-21. The project fiche itself was not available when this was written, so the "required" column has to be checked against it line by line before the final handoff.

Status words: **none** means nothing in the repository yet, **code** means code or scripts exist but nothing was verified in a cloud account, **verified** means the owner supplied sanitized evidence. Only Oussama's AWS rows are verified so far (evidence in `RUNBOOK.md`); the other rows still reflect 2026-11-21 and their owners should update them.

| Provider | Service | Role | Owner | In repo | Status | Evidence still to collect |
| --- | --- | --- | --- | --- | --- | --- |
| Azure | App Service | Voting UI and API, outbox publisher | Zakaria | `web.py`, `Dockerfile`, `deploy-azure.ps1` | code | Hosted sign-in, health probe, test ballot receipt |
| Azure | Container Apps | Kafka consumer, final ballot write | Zakaria | `kafka_worker.py`, `deploy-azure.ps1` | code | Worker log showing a stored ballot |
| Azure | Cosmos DB | Voters, sessions, outbox, encrypted ballots | Zakaria | `cosmos_store.py` | code (emulator) | Hosted write test, role assignments |
| Azure | Entra ID | Staff sign-in and roles | Zakaria | `AZURE.md` (steps only) | none | Role check on issue and admin routes |
| Azure | Application Gateway with WAF | Web edge protection | Zakaria | none | none | Rule set and a blocked request |
| Azure | Key Vault | Deployment secrets | Zakaria | none | none | Secret references, no values |
| Azure | Azure Monitor | Azure service monitoring | Zakaria | none | none | Alert rules or dashboard, exported |
| AWS | EC2 for Kafka | Broker, SASL_SSL, ACLs | Zelmati | none (`infra/aws/` absent) | none | Producer and consumer test through the private route |
| AWS | EC2 for tally | Post-close count | Zelmati | none | none | Tally output matching the fixture |
| AWS | Lambda | Technical alerts, admin notifications | Oussama | `infra/ops/lambda/` | verified 2026-11-24 (stack `electioncloud-ops`, eu-north-1), fallback to OCI verified 2026-11-25 | |
| AWS | CloudWatch | AWS monitoring | Oussama | `infra/ops/template.yaml` | verified 2026-11-24 (both `ec-selfwatch-*` alarms reached ALARM), Zelmati's `electioncloud-kafka-ec2-status` alarm routed from eu-central-1 to the Lambda verified 2026-11-25 | |
| AWS | Lambda function URL (test only) | Receives OCI fallback notifications during rehearsal | Oussama | `infra/ops/test-webhook.yaml` | verified 2026-11-24 (stack `electioncloud-test-webhook`), delivery from the OCI function verified 2026-11-25 | Delete after the demo |
| Oracle Cloud | OCI Compute standby | Standby tally | Mesbah | code (local tests) | code | Standby tally equal to primary |
| Oracle Cloud | OCI Functions | Supplemental checks, fallback notifications | Mesbah | code (setup documented) | fallback route verified 2026-11-25 with Oussama (one notification, replay answered `duplicate`) | Supplemental health checks |
| Oracle Cloud | OCI Monitoring | Google service monitoring | Mesbah | code (setup documented) | code | Signal that triggers the fallback |
| Shared | GitHub Actions CI | PR checks | Oussama | `.github/workflows/ci.yml` | code (first run pending) | Green run on a PR |

## Cross-provider contracts to confirm

| Contract | Between | Where it should be written down |
| --- | --- | --- |
| Environment variable names and health event fields | Zakaria to everyone | Zakaria's interface note |
| Kafka topic, auth and ACL scope | Zelmati to Zakaria | `infra/aws/` |
| Tally result schema (election ID, schema version, totals, total counted) | Zelmati, Zakaria, Mesbah | `infra/aws/` |
| Alert event schema | Oussama to everyone | `infra/ops/README.md` |
| Fallback invocation | Mesbah to Oussama | `infra/oci/` |
