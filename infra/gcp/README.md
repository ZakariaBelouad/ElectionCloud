# Google Cloud recovery

The Compute Engine standby runs the same post-close tally as EC2 against the same Cosmos partition. The functions report technical health and queue fallback notifications. Each can operate independently of the other.

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

Deploy three authenticated gen2 HTTP functions using the same source. Run from the repository root after approval. Configure three dedicated runtime identities. The probe identity needs only approved network access to the health endpoint. Grant the intake identity Firestore create and get access in a dedicated database/project as appropriate. The caller needs Cloud Run Invoker on its target function and sends a Google-signed ID token with the function URL as audience. Confirm that Firestore Native mode is enabled for the runtime project and that the selected database matches the default client before deploying. Grant the delivery identity only the Firestore get and update permissions and access to the specific Secret Manager version used for the webhook token.

```bash
gcloud functions deploy electioncloud-health --gen2 --runtime=python313 \
  --project='<project-id>' --region='<region>' --source=infra/gcp/functions \
  --trigger-http --no-allow-unauthenticated --entry-point=supplemental_health \
  --service-account='<health-runtime-sa>' \
  --set-env-vars='PRIMARY_HEALTH_URL=https://<approved-health-host>/<health-path>'

gcloud functions deploy electioncloud-fallback --gen2 --runtime=python313 \
  --project='<project-id>' --region='<region>' --source=infra/gcp/functions \
  --trigger-http --no-allow-unauthenticated --entry-point=fallback_notification \
  --service-account='<fallback-runtime-sa>'
```

Use authenticated GET for health and authenticated POST with application/json for fallback. The health function reports reachability of the configured HTTPS endpoint with a four-second request timeout. Person 4 chooses the probe target, interval and alert threshold. An approved caller maps the AWS technical signal to the [event fixture](fixtures/fallback-event.json), dropping the free-form summary. Use a globally unique technical event ID per state change and reuse it verbatim on retries. Send no election, ballot, voter or credential data.

Fallback returns 202 on first enqueue, 200 on exact replay, 409 on ID reuse with changed content, 400 for an invalid payload, and 503 for retryable intake errors. Retry timeouts and 503 with bounded exponential backoff and the same JSON. Firestore atomically creates one pending document per ID. Retain IDs through the full retry and replay window. A 202 confirms intake only. After 202 or a replay response of 200, the Person 4 dispatcher calls the authenticated delivery endpoint with `{"event_id":"evt-worker-0001"}`. Retry delivery timeouts and 503 with the same ID. Arrange a dispatcher or reconciler for stale pending entries if the caller stops between intake and delivery.

```bash
gcloud functions deploy electioncloud-delivery --gen2 --runtime=python313 \
  --project='<project-id>' --region='<region>' --source=infra/gcp/functions \
  --trigger-http --no-allow-unauthenticated --entry-point=deliver_notification \
  --service-account='<delivery-runtime-sa>' \
  --set-env-vars='NOTIFICATION_WEBHOOK_URL=https://<approved-webhook-host>/<path>' \
  --set-secrets='NOTIFICATION_WEBHOOK_TOKEN=<secret-name>:<version>'
```

The webhook receives the same technical event with a bearer credential and an Idempotency-Key header equal to the event ID. The provider must atomically deduplicate that key across concurrent requests and ambiguous timeouts, preserve it through the retry window, and return 2xx both for the first accepted send and its replay. Select and verify a provider and synthetic destination with Person 4 before activation. The delivery function marks the record delivered after provider acknowledgement, skips an already delivered event, and returns 404 for an unknown ID. On a 503, retry with bounded exponential backoff and the same ID. Keep pending records for operator reconciliation.

In Cloud Logging, use the JSON fields `signal`, `status`, `event_id` and `service` to diagnose requests. Configure Cloud Monitoring alerts for sustained unhealthy probes, fallback retry responses and stale pending notifications. Track the VM instance status separately. Correlate using synthetic event IDs.

## Local verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-cosmos.txt -r infra/gcp/functions/requirements.txt
.\.venv\Scripts\python.exe infra/aws/test_tally.py
.\.venv\Scripts\python.exe infra/gcp/test_recovery.py
```

The local exercise runs production tally logic against a synthetic Cosmos transport, checks the AWS aggregate fixture, simulates the publication lock and tests function responses with local fakes. Hosted verification needs approved GCP billing and IAM, Azure connectivity and operators, the final release SHA, and an agreed publication destination and notification provider. Record code SHA, VM image, timings, technical event ID and redacted audit references after the team rehearsal.
