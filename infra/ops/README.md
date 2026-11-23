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
| `service` | `web`, `worker`, `kafka`, `cosmos`, `tally`, `alerts`, `gcp-standby` |
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
4. If SNS fails, POST the same event to the Google Cloud Function in `FALLBACK_URL`.
5. If both fail, release the claim and raise. Lambda retries twice, then the event lands in the dead-letter queue. Because the claim was released, the retry is allowed to notify.

The fallback uses a Google ID token minted from the Lambda execution role via Workload Identity Federation. The private function returns HTTP 200 after successful delivery or an acknowledged replay.

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

Stage the template and the Linux x86-64 Python 3.13 Lambda package from the repository root.

```powershell
$stage = Join-Path ([IO.Path]::GetTempPath()) ('electioncloud-ops-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path "$stage/lambda" | Out-Null
Copy-Item infra/ops/template.yaml "$stage/template.yaml"
Copy-Item infra/ops/lambda/*.py "$stage/lambda"
python -m pip install --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.13 --only-binary=:all: --target "$stage/lambda" -r infra/ops/lambda/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Lambda dependency staging failed.' }
aws cloudformation package --template-file "$stage/template.yaml" --s3-bucket <bucket> --output-template-file "$stage/packaged.yaml"
aws cloudformation deploy --template-file "$stage/packaged.yaml" --stack-name electioncloud-ops --capabilities CAPABILITY_IAM
```

The first deployment leaves fallback disabled and outputs AlertFunctionRoleArn. On Google Cloud, enable STS and IAM Service Account Credentials, and configure an AWS Workload Identity Federation provider for the router's AWS account. Restrict the provider condition to the STS assumed-role ARN for that exact Lambda execution role. Grant the corresponding federated role principal roles/iam.workloadIdentityUser on a dedicated Google invoker service account. Grant that service account roles/run.invoker on the fallback function's underlying Cloud Run service. Use the full IAM provider resource name starting with //iam.googleapis.com/ as GoogleWifAudience.

Update the same stack using the packaged template and the approved fallback URL and invoker identity. Set FallbackUrl to the exact HTTPS URL the function accepts as its ID-token audience.

```powershell
aws cloudformation deploy --template-file "$stage/packaged.yaml" --stack-name electioncloud-ops --capabilities CAPABILITY_IAM `
  --parameter-overrides 'FallbackUrl=<private HTTPS function URL>' 'GoogleWifAudience=<full provider resource>' 'GoogleInvokerServiceAccount=<invoker email>'
```

Allow HTTPS egress to Google STS, IAM Credentials, the private authenticated function URL and the AWS service endpoints used by the router. Verify authentication and delivery against an approved synthetic destination before enabling the shared route. Exercise a primary notification failure and replay the same event ID. Confirm one delivery and verify that an unrelated role cannot invoke the function.
