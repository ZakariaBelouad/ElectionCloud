# Ops and integration (Person 4)

This directory holds alerting and the notes that tie the four tracks together. Workflows live in `.github/workflows/`, cross-service tests in `tests/integration/`.

Nothing here is deployed yet. Creating the AWS stack costs a little money and sends mail, so it waits for the team's approval.

## Contents

| File | Purpose |
| --- | --- |
| `lambda/alert_handler.py` | Alert router: validate, deduplicate, notify, fall back, retry |
| `template.yaml` | CloudFormation: Lambda, DynamoDB dedup table, SNS topic, EventBridge rule, dead-letter queue, self-watch alarms |
| `fixtures/` | Sample events: worker unhealthy, Kafka unavailable, Cosmos write failures, recovery, two invalid ones, one CloudWatch alarm |
| `ONBOARDING.md` | Clone, branch, PR flow and repository settings Zakaria has to apply |
| `DEPLOYMENT-INVENTORY.md` | Required services, owner, evidence status |
| `RUNBOOK.md` | Final runbook, monitoring per provider, cleanup owners |

## Alert event contract

One small JSON object. Anything not listed is rejected.

```json
{
  "event_id": "evt-kafka-0001",
  "service": "kafka",
  "severity": "critical",
  "observed_at": "2026-11-21T10:05:00Z",
  "status": "firing",
  "summary": "Broker unreachable from publisher"
}
```

| Field | Rule |
| --- | --- |
| `event_id` | 8 to 128 characters of letters, digits and `. _ : -`. Stable per incident transition, so a retry sends the same ID |
| `service` | `web`, `worker`, `kafka`, `cosmos`, `tally`, `alerts`, `oci-standby` |
| `severity` | `info`, `warning`, `critical` |
| `observed_at` | ISO 8601, UTC, ending in `Z` |
| `status` | `firing` or `resolved` |
| `summary` | Optional, up to 200 characters of plain technical text. Refused if it contains words like voter, ballot, candidate, token, password, or a long random-looking string |

No voter identifiers, vote choices, session tokens or keys, in any field. Persons 1 to 3 should emit exactly these fields.

CloudWatch alarms named `electioncloud-<service>-...` are picked up by the EventBridge rule and converted into this format. `ALARM` becomes `critical` and `firing`, `OK` becomes `info` and `resolved`.

## What happens to an event

1. Validate. Invalid events are logged and dropped, nothing is sent.
2. Claim the `event_id` in DynamoDB (24 hour expiry). A second event with the same ID is a duplicate and sends nothing.
3. Publish to the SNS administrator topic.
4. If SNS fails, POST the same event to the OCI API Gateway fallback route in `FALLBACK_URL`.
5. If both fail, release the claim and raise. Lambda retries twice, then the event lands in the dead-letter queue. Because the claim was released, the retry is allowed to notify.

The Lambda reads the fallback bearer credential from AWS Secrets Manager. The OCI function validates it against OCI Vault and returns HTTP 200 after successful delivery or an acknowledged replay.

The router also watches itself. Two alarms (`ec-selfwatch-*`) go straight to the SNS topic, without passing through the router, when the function errors or when delivery fails on every route.

## Run it locally

Needs Python 3.10 or newer, nothing else. No AWS account, no network.

```powershell
python -m unittest discover -s tests -t . -v
```

The tests use `MockSender` and an in-memory dedup store. They cover valid and invalid events, the alarm mapping, five repeats of one event giving one notification, expiry of the dedup entry, SNS failure falling back to the second route, total failure followed by a successful retry, and a check that messages and logs hold no sensitive words.

## Local equivalents of every CI step

| CI step | Run on your PC |
| --- | --- |
| Repository hygiene | `python tests/integration/check_repo_hygiene.py` |
| Lint | `python -m pip install ruff` then `ruff check --select E9,F .` |
| Tests | `python -m unittest discover -s tests -t . -v` |
| CloudFormation lint | `python -m pip install cfn-lint` then `cfn-lint infra/ops/template.yaml -i W3002` |
| Docker build | `docker build --target web -t electioncloud-web:ci .` and the same with `--target worker` |
| Compose file | `docker compose config --quiet` |
| Synthetic vote | `python tests/integration/smoke_compose.py` |

On `cfn-lint`: put the template path before `-i`. The `-i` option swallows the next argument otherwise and waits on stdin.

## Deploying the stack (after approval only)

Package and deploy from the repository root. Leave FallbackUrl empty until the OCI endpoint is ready.

```powershell
aws cloudformation package --template-file infra/ops/template.yaml --s3-bucket <bucket> --output-template-file packaged.yaml
aws cloudformation deploy --template-file packaged.yaml --stack-name electioncloud-ops --capabilities CAPABILITY_IAM
```

Set up the [OCI fallback endpoint](../oci/README.md#managed-functions). Put the same high-entropy bearer credential in OCI Vault and AWS Secrets Manager as plain secret text. Use the AWS-managed Secrets Manager encryption key or explicitly grant the execution role decrypt access to the approved customer-managed key. CloudFormation grants read access only to the supplied secret ARN. Update the stack with the HTTPS route and secret ARN. Do not pass secret contents as a stack parameter.

```powershell
aws cloudformation deploy --template-file packaged.yaml --stack-name electioncloud-ops --capabilities CAPABILITY_IAM `
  --parameter-overrides 'FallbackUrl=<OCI gateway /recovery/fallback URL>' 'FallbackSecretArn=<AWS secret ARN>'
```

Verify synthetic delivery and replay with the approved test destination. Confirm that missing or invalid bearer credentials are rejected and that replaying the same event ID results in a single notification. Coordinate credential rotation in both stores.
