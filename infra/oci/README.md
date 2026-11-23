# Oracle Cloud recovery

OCI Compute runs the same post-close tally revision as AWS EC2 against the authoritative Azure Cosmos partition. Two managed OCI Functions provide supplemental health and fallback notification. OCI API Gateway exposes their HTTPS routes and OCI Monitoring and Logging provide operational visibility.

## Standby VM

1. After resource approval, use the designated OCI tenancy, compartment, region and network. In the OCI console create a Linux instance named `electioncloud-standby` from an approved Ubuntu LTS image. Record the image OCID, shape, subnet OCID and launch configuration. For a Free Tier demo, select an Always Free eligible shape and image, subject to account limits and capacity.
2. Use a private subnet, an approved SSH public key, and OCI Bastion or the team's managed private administration path. Use network security groups to restrict SSH to that path. The VM needs approved egress for packages and Azure HTTPS endpoints.
3. Install Git, Python 3 with venv support, and Azure CLI from approved sources. Clone the reviewed repository and use the exact full commit running on EC2.

   ```bash
   git switch --detach '<full-ec2-release-sha>'
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements-cosmos.txt
   git rev-parse HEAD
   ```

4. For private Azure endpoints, coordinate routed connectivity and private DNS forwarding between OCI and Azure. Verify TLS to the same Cosmos, Key Vault and result storage hostnames used by EC2. The designated tally operator uses the [AWS tally identity and key procedure](../aws/RUNBOOK.md#primary-tally-host) with their own Azure access. Keep the key outside OCI function configuration.
5. Confirm the outbox drained, the election closed, and the standby sees the authoritative final accepted turnout. The standby uses a direct read. Pause if the authoritative data cannot be verified. The demo target is 10 minutes from confirmed primary failure with a ready VM and available operators. Use the [manual failover runbook](FAILOVER.md) and record the actual time.

## Managed functions

Create an OCI Functions application with an approved subnet and OCI Container Registry repository. Build and push the image from `infra/oci/functions` using the Fn CLI and its configured OCI registry context (`fn build` followed by tagging and pushing the built image to OCIR). Create **two distinct OCI Functions** using that same reviewed image by digest. Use 512 MB memory, a 15-second timeout and architecture compatible with the built image. Record the image digest and function OCIDs. OCI lists managed Functions under its time-limited trial. Verify that the account, registry and API Gateway can support the demo through its scheduled date.

| Function | Configuration |
| --- | --- |
| `electioncloud-health` | `RECOVERY_MODE=health`, `CALLER_SECRET_OCID`, `PRIMARY_HEALTH_URL` |
| `electioncloud-fallback` | `RECOVERY_MODE=fallback`, `CALLER_SECRET_OCID`, `WEBHOOK_SECRET_OCID`, `NOTIFICATION_WEBHOOK_URL`, `EVENT_NAMESPACE`, `EVENT_BUCKET` |

Create a dedicated private standard Object Storage bucket for technical event records. Scope the fallback function resource principal to read, create and overwrite objects in that bucket. Keep the records through the replay window. Grant each function resource principal read access to its specific OCI Vault secret bundles. The fallback caller secret contains the same random bearer credential as the AWS Secrets Manager secret, as plain text in both stores. Use an independent health caller credential and an independent webhook credential. Use HTTPS egress to OCI services and the approved URLs. Avoid logging credentials and event bodies.

Create an HTTPS OCI API Gateway deployment at `/recovery`, mapping `GET /health` and `POST /fallback` to their respective Oracle Functions backends. Permit the gateway resource principal to invoke only the required functions through OCI IAM. For AWS access from outside OCI, use a reachable gateway and forward the Authorization header intact. The handlers reject missing or incorrect credentials before probing or processing alerts. Set request limits and avoid logging the Authorization header. Invoke the public gateway only with the approved credential. Functions are invoked through the IAM-authorized gateway.

Use the [technical event fixture](fixtures/fallback-event.json). An HTTP 200 acknowledges confirmed delivery or a completed replay, 400 rejects invalid data, 401 and 403 reject authentication, 409 rejects ID reuse with changed technical data, and 503 signals a retryable error. Retries must send the same event ID and technical fields. The optional summary is discarded. The webhook must atomically deduplicate the `Idempotency-Key` across timeouts and concurrent attempts and acknowledge successful replays with 2xx. Object Storage creates the pending event conditionally and records delivery using its ETag after acknowledgement. A provider acknowledgement followed by a failed storage update can replay safely only if the provider honors the key.

Configure OCI Monitoring and Logging for probe failures, function errors and duration, API Gateway failures and VM availability. Investigate stale pending event records and coordinate retries with Ops. Test that missing or wrong credentials are denied, route an approved synthetic alert through AWS with SNS unavailable, and verify delivery once after replay.

## Local verification

From the repository root, install `requirements-cosmos.txt` and run:

```powershell
python infra/aws/test_tally.py
python infra/oci/test_recovery.py
python -m unittest discover -s tests -t .
```

The local exercise tests conditional event writes with a fake OCI client and the real tally logic with a synthetic Cosmos transport. Hosted verification needs the approved tenancy and trial or billing coverage, Azure access, the final EC2 release, and an approved webhook destination.
