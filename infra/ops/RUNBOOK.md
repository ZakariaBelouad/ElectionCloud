# ElectionCloud runbook (draft for the final handoff)

This is the skeleton Oussama completes with evidence from the other three owners. Cells marked TBD are unknown today and must be filled by the person named, not guessed.

## Monitoring by provider

| Provider | Tool | Watches | Signals to expose | Owner | Where the config lives |
| --- | --- | --- | --- | --- | --- |
| Azure | Azure Monitor | App Service, Container Apps, Cosmos | web `/healthz`, worker running, Cosmos write failures | Zakaria | TBD |
| AWS | CloudWatch | Kafka EC2, tally EC2, Lambda | Kafka unavailable, VM status, router errors, delivery failures | Zelmati for the VMs, Oussama for Lambda | `infra/ops/template.yaml` (Lambda part) |
| Google Cloud | Cloud Monitoring | Standby VM, functions | Standby ready, function errors | Mesbah | TBD |

Every signal that should reach administrators is sent as an alert event (schema in `infra/ops/README.md`) or as a CloudWatch alarm named `electioncloud-<service>-<what>`.

## Common situations

| Situation | First check | Who acts |
| --- | --- | --- |
| Ballot stays "queued" | Worker log on Azure for the topic and a stored-ballot line, then broker reachability | Zakaria, then Zelmati |
| Close refuses because the outbox is not empty | Wait for the worker to drain it, do not force | Operator |
| Alert flood | Check that event IDs are stable per incident, duplicates are dropped for 24 hours | Oussama |
| No alert arrived | Router errors alarm, dead-letter queue, then the Google fallback log | Oussama, Mesbah |
| Primary tally host down after close | Confirm closure, then the failover runbook in `infra/gcp/` | Mesbah |

## Cleanup owners

Fill these in when resources are approved. A resource without a named owner does not get created.

| Resource | Created by | Cleanup owner | Cleanup command or step | Done |
| --- | --- | --- | --- | --- |
| Azure resource group | TBD | TBD | TBD | |
| AWS Kafka EC2, tally EC2 | TBD | TBD | TBD | |
| AWS `electioncloud-ops` stack | TBD | TBD | `aws cloudformation delete-stack --stack-name electioncloud-ops` | |
| Google standby VM and functions | TBD | TBD | TBD | |

## Evidence collected

One line per piece of sanitized evidence, with owner, date and commit. Nothing collected yet.

## Still pending

List every check that was only done locally or with mocks, with the owner who can close it. The starting point is the "Status" column of `DEPLOYMENT-INVENTORY.md`.
