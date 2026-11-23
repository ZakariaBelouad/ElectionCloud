# Google Cloud recovery

The Compute Engine standby runs the same post-close tally as EC2 against the same Cosmos partition. The functions report technical health and deliver fallback notifications. Each can operate independently of the other.

## Standby host

After billable-resource approval, use the GCP project and zone agreed for the demo. Record the exact approved Ubuntu 24.04 LTS image, EC2 release commit, and Python dependency versions. The commands assume a preconfigured private subnet and IAP firewall rule restricted to SSH on tagged hosts. Grant authorized operators IAP tunnel and OS Login access. Use a dedicated VM service account without Azure or tally-key permissions.

```bash
gcloud compute instances create electioncloud-standby \
  --project='<project-id>' --zone='<zone>' --subnet='<subnet>' \
  --image='<pinned-ubuntu-image>' --image-project=ubuntu-os-cloud \
  --machine-type=e2-small --no-address --tags=electioncloud-standby \
  --service-account='<standby-sa>@<project-id>.iam.gserviceaccount.com' \
  --metadata=enable-oslogin=TRUE

gcloud compute ssh electioncloud-standby --project='<project-id>' \
  --zone='<zone>' --tunnel-through-iap
```

Install Git, Python 3 with venv support, and Azure CLI from approved sources. Use approved egress or mirrors. Clone through the team's reviewed repository access method into a protected checkout. Fetch the exact release commit from Person 2 and install the same Cosmos dependencies.

```bash
git switch --detach '<full-ec2-release-sha>'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cosmos.txt
git rev-parse HEAD
```

Use the same Azure Cosmos HTTPS hostname and database, container, and election ID as EC2. For Azure private endpoints, the GCP VPC needs an approved routed connection to Azure and DNS forwarding for the applicable private zones. From the VM verify DNS, TLS and connectivity for Cosmos, Key Vault, and the result store using their approved hostnames. Verify the authorized Entra user can read the demo partition with Cosmos data-plane read access and has a separate approved key workflow. The Azure CLI login and Cosmos environment names are in the [AWS tally runbook](../aws/RUNBOOK.md).

Person 1 must confirm the outbox has drained, the authoritative election is closed and final accepted turnout is known. Require the standby to observe that same closed status and count. This design uses a direct read and has no snapshot import path. Pause the demonstration if that read cannot be verified. Target a manual recovery within 10 minutes from confirmed failure when the VM is ready and operators are available. Time the shared cloud demo before reporting a measured result.

## Functions and Person 4 handoff

Deploy two authenticated gen2 HTTP functions using the same source. Run from the repository root after approval. Configure two dedicated runtime identities. The probe identity needs only approved network access to the health endpoint. Grant the fallback identity Firestore create, get and update access in a dedicated database/project as appropriate. The caller needs Cloud Run Invoker on its target function and sends a Google-signed ID token with the function URL as audience. Confirm that Firestore Native mode is enabled for the runtime project and that the selected database matches the default client before deploying. Grant the fallback identity access to the specific Secret Manager secret used for the webhook token.

```bash
gcloud functions deploy electioncloud-health --gen2 --runtime=python313 \
  --project='<project-id>' --region='<region>' --source=infra/gcp/functions \
  --trigger-http --no-allow-unauthenticated --entry-point=supplemental_health \
  --service-account='<health-runtime-sa>' \
  --set-env-vars='PRIMARY_HEALTH_URL=https://<approved-health-host>/<health-path>'

gcloud functions deploy electioncloud-fallback --gen2 --runtime=python313 \
  --project='<project-id>' --region='<region>' --source=infra/gcp/functions \
  --trigger-http --no-allow-unauthenticated --entry-point=fallback_notification \
  --service-account='<fallback-runtime-sa>' --timeout=15s \
  --set-env-vars='NOTIFICATION_WEBHOOK_URL=https://<approved-webhook-host>/<path>' \
  --set-secrets='NOTIFICATION_WEBHOOK_TOKEN=<secret-name>:<version>'
```

Use authenticated GET for health and authenticated POST with application/json for fallback. The health function reports reachability of the configured HTTPS endpoint with a four-second request timeout. Person 4 chooses the probe target, interval and alert threshold. The AWS router uses one HTTPS POST with its existing event JSON. The fallback accepts the optional summary field and discards it before logging, storage or delivery. Send no election, ballot, voter or credential data. Use a globally unique technical event ID per state change and reuse it verbatim on retries. See the [fixture](fixtures/fallback-event.json).

The fallback returns 200 after webhook acknowledgement and Firestore update, including when the event was already delivered. It returns 409 on ID reuse with changed technical content, 400 for an invalid payload, and 503 for retryable storage or delivery failures. Retry timeouts and 503 with bounded backoff and identical technical fields. Firestore atomically creates one record per ID. Retain records through the retry window.

The webhook receives the technical event with a bearer credential and an Idempotency-Key header equal to the event ID. It must atomically deduplicate that key across concurrent requests and ambiguous timeouts and acknowledge an accepted replay with 2xx. The fallback marks the record delivered after acknowledgement. Confirm an approved provider and synthetic destination before activation.

Keep the fallback private. Configure the Lambda execution role and Google Workload Identity Federation using the [Ops deployment instructions](../ops/README.md#deploying-the-stack-after-approval-only). Verify the live token exchange and retries against the approved private function URL.

In Cloud Logging, use the JSON fields `signal`, `status`, `event_id` and `service` to diagnose requests. Configure Cloud Monitoring alerts for sustained unhealthy probes, fallback retry responses and stale pending notifications. Track the VM instance status separately. Correlate using synthetic event IDs.

## Local verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-cosmos.txt -r infra/gcp/functions/requirements.txt
.\.venv\Scripts\python.exe infra/aws/test_tally.py
.\.venv\Scripts\python.exe infra/gcp/test_recovery.py
```

The local exercise runs production tally logic against a synthetic Cosmos transport, checks the AWS aggregate fixture, simulates the publication lock and tests function responses with local fakes. Hosted verification needs approved GCP billing and IAM, Azure connectivity and operators, the final release SHA, and an agreed publication destination and notification provider. Record code SHA, VM image, timings, technical event ID and redacted audit references after the team rehearsal.
