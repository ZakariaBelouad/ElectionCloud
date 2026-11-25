# Release checklist and shared demo rehearsal

Owner: Oussama. Fill this in when you cut a release. Keep one copy per release tag, and keep tokens, keys and secrets out of it.

## Release record

| Item | Value |
| --- | --- |
| Release tag | |
| Commit SHA | |
| Image tag (web, worker) | |
| Shared election ID (fresh, never reused) | |
| Date and who ran it | |

## Component status at this revision

| Component | Owner | Interface | Latest tested commit | Deployed? | Blocker |
| --- | --- | --- | --- | --- | --- |
| Azure web, publisher, worker, Cosmos | Zakaria | env names, `/healthz`, topic name | | | |
| Kafka EC2 | Zelmati | broker DNS and port, TLS, ACL scope | | | |
| Tally EC2 | Zelmati | tally command, result schema | | | |
| Oracle standby and functions | Mesbah | tally invocation, fallback event | | | |
| Lambda alerts | Oussama | alert event schema | `2fdae78` | Yes, AWS eu-north-1, stacks `electioncloud-ops` and `electioncloud-test-webhook` | None. OCI fallback verified 2026-11-25 with Mesbah (`RUNBOOK.md`) |

### Azure hosting choice

Confirmed by Zakaria on 2026-11-25. Update this table when he confirms the switch.

| Option | Status | Condition to switch |
| --- | --- | --- |
| Azure Container Apps | Current deployment | |
| App Service, Austria East | Being validated | Private connection from the app to Kafka tested by Zakaria and Zelmati |

Write the hosting actually used for the rehearsal in the "Deployed?" column of the Azure row above.

## Before the rehearsal

- [ ] CI is green on the release commit
- [ ] `python tests/integration/smoke_compose.py --evidence smoke-evidence.json` passes on at least one teammate's PC, same commit
- [ ] Every owner has cloud access through their own identity, and secrets sit in the provider's secret store
- [ ] Billable resources have been approved by the team, with a named cleanup owner for each (see `infra/ops/RUNBOOK.md`)
- [ ] Alert destination is an authorized test address, not a real list

## Rehearsal, in order

Write one expected and one observed result per line. "Local" means the Compose smoke test covers it. "Cloud" needs the shared environment.

| # | Check | Expected | Observed | Covered by | Pass |
| --- | --- | --- | --- | --- | --- |
| 1 | Staff signs in and issues a one-time session | One token, second session for the same voter refused | | Local (issue part), Cloud (Entra role) | |
| 2 | Cast a ballot | Receipt id, or "queued" then a receipt after the worker stores it | | Local, Cloud | |
| 3 | Check the receipt with the same token | Same receipt id | | Local | |
| 4 | Retry and replay | Reusing the token adds nothing, turnout unchanged | | Local (token reuse). Kafka message replay: Cloud or a Kafka client test | |
| 5 | Turnout during voting | Count of stored ballots, no candidate totals visible | | Local, Cloud | |
| 6 | Tally before close | Refused | | Local | |
| 7 | Close the election | Closed once the outbox is empty, new sessions refused | | Local, Cloud | |
| 8 | AWS tally | Totals equal the synthetic fixture, key held only by the operator | | Cloud | |
| 9 | Publish results | One result published, shown on the dashboard after close only | | Cloud | |
| 10 | Technical alert | Simulated Kafka or worker alert reaches the test destination once, repeating it adds nothing | | Local (mock), Cloud | |
| 11 | Notification failure | Primary route down, fallback delivers | | Local (mock), Cloud | |
| 12 | Oracle standby tally | Same totals as the primary | | Cloud | |
| 13 | Failover guard | Only one tally is published for the election | | Cloud | |

## After the rehearsal

- [ ] Sanitized logs and screenshots collected from each owner (no tokens, no keys, no voter references)
- [ ] Anything not verified is listed in `infra/ops/DEPLOYMENT-INVENTORY.md` with its owner
- [ ] Every cloud resource deleted by its cleanup owner, or the reason it stays is written here
