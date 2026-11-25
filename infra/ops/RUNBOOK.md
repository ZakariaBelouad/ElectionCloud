# ElectionCloud runbook (draft for the final handoff)

This is the skeleton Oussama completes with evidence from the other three owners. Cells marked TBD are unknown today and must be filled by the person named, not guessed.

## Monitoring by provider

| Provider | Tool | Watches | Signals to expose | Owner | Where the config lives |
| --- | --- | --- | --- | --- | --- |
| Azure | Azure Monitor | App Service, Container Apps, Cosmos | web `/healthz`, worker running, Cosmos write failures | Zakaria | TBD |
| AWS | CloudWatch | Kafka EC2, tally EC2, Lambda | Kafka unavailable, VM status, router errors, delivery failures | Zelmati for the VMs, Oussama for Lambda | `infra/ops/template.yaml` (Lambda part) |
| Oracle Cloud | OCI Monitoring | Standby VM, functions | Standby ready, function errors | Mesbah | TBD |

Every signal that should reach administrators is sent as an alert event (schema in `infra/ops/README.md`) or as a CloudWatch alarm named `electioncloud-<service>-<what>`.

## Common situations

| Situation | First check | Who acts |
| --- | --- | --- |
| Ballot stays "queued" | Worker log on Azure for the topic and a stored-ballot line, then broker reachability | Zakaria, then Zelmati |
| Close refuses because the outbox is not empty | Wait for the worker to drain it, do not force | Operator |
| Alert flood | Check that event IDs are stable per incident, duplicates are dropped for 24 hours | Oussama |
| No alert arrived | Router errors alarm, dead-letter queue, then the Oracle fallback log | Oussama, Mesbah |
| Primary tally host down after close | Confirm closure, then the failover runbook in `infra/oci/` | Mesbah |

## Alert route checks (rehearsal)

Run in AWS CloudShell, eu-north-1, from `~/ElectionCloud`. Every check uses a fictitious event with a fresh ID, because the router drops a repeated ID for 24 hours.

```bash
FN=electioncloud-alert-router-electioncloud-ops
new_event() {
  printf '{"event_id":"evt-rehearsal-%s","service":"kafka","severity":"critical","observed_at":"%s","status":"firing","summary":"Rehearsal alert, fictitious"}' \
    "$(date +%s)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
send() { aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out --payload "$1" out.json >/dev/null; cat out.json; echo; }
```

### A. Primary route (SNS)

1. `EVENT=$(new_event); send "$EVENT"` gives `"result": "sent", "route": "primary"`.
2. `send "$EVENT"` again gives `"result": "duplicate"`.
3. Exactly one email arrives at the test address.

### B. Fallback route (OCI)

Needs, before starting: Mesbah's `/recovery/fallback` URL, the caller secret in both vaults, the webhook secret in OCI Vault, and the stack updated with `FallbackUrl` and `FallbackSecretArn` (keep the current `AdminEmail`).

Secrets call (Oussama and Mesbah, about 15 minutes, values never written in chat, email, tickets or the repo):

1. Webhook secret, already generated: Oussama opens Secrets Manager in eu-north-1, the secret of the `electioncloud-test-webhook` stack, "Retrieve secret value", and reads it out. Mesbah pastes it into a new OCI Vault secret and sets `WEBHOOK_SECRET_OCID` on his fallback function.
2. Caller secret, created during the call in CloudShell, without printing it:
   ```bash
   CALLER_ARN=$(aws secretsmanager create-secret --name electioncloud/oci-fallback-caller \
     --description "Bearer the alert router sends to the OCI /recovery/fallback route" \
     --secret-string "$(openssl rand -hex 32)" --query ARN --output text)
   echo "$CALLER_ARN"
   ```
   Oussama reads the value from the console the same way, Mesbah stores it in OCI Vault and sets `CALLER_SECRET_OCID`.
3. Once the route answers, update the stack (the `deploy` command from the deployment plan) with `FallbackUrl=<route URL>`, `FallbackSecretArn=$CALLER_ARN` and the current `AdminEmail`.
4. Mesbah checks the caller secret without revealing it: a POST without bearer to his route gets 401, the Lambda's first fallback call gets 200.

1. Break the primary route as in step 5 of the deployment plan (save the environment to `env-backup.json`, append `-missing` to `ADMIN_TOPIC_ARN`).
2. `EVENT=$(new_event); send "$EVENT"` gives `"result": "sent", "route": "fallback"`, logs show `primary_failed` then `sent` with `"route": "fallback"`.
3. Mesbah checks the OCI function log: one accepted event with that ID.
4. The test webhook log shows one `received` line for that ID: `aws logs tail /aws/lambda/electioncloud-test-webhook-electioncloud-test-webhook --since 10m --format short | grep msg`.
5. Replay at the OCI side: Mesbah posts the same event to his route a second time. Replaying through the Lambda does not reach OCI, because the router already drops a repeated `event_id` for 24 hours. Expected 200 from his route and either no new webhook call or a single `duplicate` line on the webhook, never a second `received`.
6. Restore the Lambda environment from `env-backup.json` and check `ADMIN_TOPIC_ARN` no longer ends with `-missing`.
7. Both down: with the primary broken, Mesbah makes his route answer 503 (or we point `FallbackUrl` at a wrong path). Expected `NotificationFailed`, logs `primary_failed`, `fallback_failed`, `notification_failed`, and the `ec-selfwatch-*` alarms email the admins. Restore everything afterwards.

## Cleanup owners

Fill these in when resources are approved. A resource without a named owner does not get created.

| Resource | Created by | Cleanup owner | Cleanup command or step | Done |
| --- | --- | --- | --- | --- |
| Azure resource group | TBD | TBD | TBD | |
| AWS Kafka EC2, tally EC2 | TBD | TBD | TBD | |
| AWS `electioncloud-ops` stack (eu-north-1) | Oussama, 2026-11-24 | Oussama | `aws cloudformation delete-stack --stack-name electioncloud-ops` | |
| AWS `electioncloud-test-webhook` stack (eu-north-1, includes one Secrets Manager secret and one DynamoDB table) | Oussama, 2026-11-24 | Oussama | `aws cloudformation delete-stack --stack-name electioncloud-test-webhook` | |
| AWS deploy bucket `electioncloud-ops-deploy-<account>-eu-north-1` | Oussama, 2026-11-24 | Oussama | `aws s3 rb "s3://$BUCKET" --force` after both stacks are gone | |
| AWS fallback caller secret `electioncloud/oci-fallback-caller` (Secrets Manager) | Oussama, 2026-11-25 | Oussama | `aws secretsmanager delete-secret --secret-id electioncloud/oci-fallback-caller` | |
| Oracle standby VM and functions | TBD | TBD | TBD | |

## Evidence collected

One line per piece of sanitized evidence, with owner, date and commit. All AWS checks below ran in CloudShell, eu-north-1, on commit `2fdae78`, against the stack `electioncloud-ops`. The fallback route was added to the stack on 2026-11-25; checks before that ran without it. The OCI fallback function used in the 2026-11-25 checks ran commit `b2af4ac` (Mesbah).

| Date | Owner | Check | Observed |
| --- | --- | --- | --- |
| 2026-11-24 | Oussama | Stack deploy, SNS email subscription | `Successfully created/updated stack`, subscription confirmed |
| 2026-11-24 | Oussama | Same alert sent twice (`evt-demo-1795486519`, worker, critical) | First call `{"result": "sent", "route": "primary"}`, second `{"result": "duplicate"}`, no email found at the first test address |
| 2026-11-25 | Oussama | Same alert sent twice to the demo address (`evt-demo-1795567380`, worker, critical) | First call `{"result": "sent", "route": "primary"}`, second `{"result": "duplicate"}`, exactly one email "ElectionCloud worker firing" received |
| 2026-11-24 | Oussama | Self-watch alarm emails during the SNS failure test | Both `ec-selfwatch-router-errors` and `ec-selfwatch-delivery-failed` ALARM emails received at the demo address |
| 2026-11-24 | Oussama | Alert with a `voter_reference` field (`fixtures/invalid_voter_field.json`) | `{"result": "rejected", "reason": "Unexpected fields: voter_reference"}`, no email |
| 2026-11-24 | Oussama | Router logs for the three calls | Only `sent`, `duplicate`, `invalid_event` lines, no voter or ballot data |
| 2026-11-24 | Oussama | SNS failure (topic ARN suffixed with `-missing`, then restored) | `NotificationFailed`, logs `primary_failed` (`AuthorizationErrorException`) then `notification_failed`, both `ec-selfwatch-*` alarms went to ALARM and emailed, configuration restored and checked |
| 2026-11-24 | Oussama | Test webhook (`test-webhook.yaml`), first version | POST without or with a wrong bearer 401, with the right bearer 200, GET 405 (GET also checked by Mesbah from the OCI VM) |
| 2026-11-25 | Oussama | OCI fallback route `/recovery/fallback` (af-casablanca-1), POST without bearer from CloudShell | `401 {"error": "bearer credential required"}`. This check runs before the caller secret is read, so it does not prove the Vault setup |
| 2026-11-25 | Oussama | Stack updated with `FallbackUrl` and `FallbackSecretArn` (`electioncloud/oci-fallback-caller`) | `UPDATE_COMPLETE`, router environment shows both values, SNS topic unchanged |
| 2026-11-25 | Oussama, Mesbah | SNS failure with fallback enabled (`evt-rehearsal-1795577482`, 03:31 UTC) | `NotificationFailed`, logs `primary_failed` (`AuthorizationErrorException`), `fallback_failed` (HTTP 503 from the OCI route), `notification_failed`. No call reached the test webhook. Both `ec-selfwatch-*` ALARM emails received at the demo address. Configuration restored and checked. Mesbah's log: the caller secret read in Vault failed (`caller_secret_error`, `ServiceError`) |
| 2026-11-25 | Oussama, Mesbah | Same test after Mesbah checked the secret OCIDs (`evt-rehearsal-1795578182`, 03:43 UTC) | Same result: HTTP 503 from the OCI route about 3 s after the call, `notification_failed`, no call reached the test webhook. Mesbah's log: same caller secret read failure, Vault answered 404 `NotAuthorizedOrNotFound` on the CURRENT version. Configuration restored and checked |
| 2026-11-25 | Oussama, Mesbah | Same test after Mesbah fixed the IAM policy for the caller secret (`evt-rehearsal-1795578727`, 03:52 UTC) | Route gives 403 to a wrong bearer, and the router's bearer was accepted (no 403), so the caller secret matches on both sides. Still HTTP 503 after the check, `notification_failed`, no call reached the test webhook. Mesbah's log: the PUT to the `electioncloud-fallback-events` bucket got 404, `fallback_error` `ServiceError`. Configuration restored and checked |
| 2026-11-25 | Oussama, Mesbah | Same test after Mesbah granted the function access to the bucket objects (`evt-rehearsal-1795579110`, 03:58 UTC) | Lambda result `{"result": "sent", "route": "fallback"}`. Router logs `primary_failed` (`AuthorizationErrorException`) then `sent` `"route": "fallback"`. Test webhook logs one `received` line for that ID, without the `summary` field. Configuration restored and checked |
| 2026-11-25 | Mesbah, Oussama | Replay of the same POST directly on the OCI route (`evt-rehearsal-1795579110`, 04:00:33 UTC) | OCI answered 200 `{"status": "duplicate"}`. The test webhook got no new call and still has exactly one `received` line for that ID |
| 2026-11-25 | Oussama | Test webhook with Idempotency-Key deduplication, same key posted twice | First POST 200 `"duplicate": false` and a `received` log line, replay 200 `"duplicate": true` and only a `duplicate` log line, no key 400, wrong bearer 401 |

## Still pending

List every check that was only done locally or with mocks, with the owner who can close it. The starting point is the "Status" column of `DEPLOYMENT-INVENTORY.md`.

- An `electioncloud-*` CloudWatch alarm from the Kafka or tally EC2 reaching the router through EventBridge. Zelmati and Oussama.
