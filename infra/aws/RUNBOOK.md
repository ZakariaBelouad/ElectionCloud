# ElectionCloud AWS operator runbook

The academic demo uses two separate EC2 Linux hosts in private AWS subnets. Obtain approval before provisioning or deploying billable resources. Use an approved, supported Ubuntu LTS image, private administration through Systems Manager Session Manager, IMDSv2 and encrypted EBS on both hosts. Use distinct instance roles and security groups. The broker needs Docker Engine and the Docker Compose v2 plugin. Install these from the approved package source. The tally host needs Git, Python 3, venv and Azure CLI. Use approved egress or mirrors for packages and images.

## Broker host

1. Use nonoverlapping Azure and AWS network ranges with an approved site-to-site VPN and return routes. Limit broker inbound TCP 9094 to the integrated Azure workload subnet ranges that run the Kafka client. Add the App Service integration subnet when it hosts the producer. Publish no public address and open no controller port. Create a private DNS A record for the private EC2 address. Forward the AWS zone from Azure to a Route 53 Resolver inbound endpoint over the private route, or use the team's equivalent private DNS. Limit DNS inbound UDP/TCP 53 to the designated resolver source, and verify the answer from each participating Azure runtime. The Compose service resolves its own advertised name internally to loopback.
2. Attach a dedicated encrypted EBS volume. Verify the volume ID, device and filesystem by inspecting `lsblk -o NAME,SERIAL,FSTYPE,UUID,MOUNTPOINTS`. Have the infrastructure operator prepare a filesystem on the confirmed blank volume, persist the mount by filesystem UUID in `/etc/fstab`, and mount at `/srv/electioncloud-kafka`. Confirm the mount before creating the data directory. A data subdirectory keeps filesystem metadata outside Kafka's log path. Preserve the volume on replacement and use approved snapshots where required.
3. Put the reviewed repository revision at `/opt/electioncloud` using the approved private-repo access method. Kafka uses `apache/kafka:4.4.0`, with Java 25 in the tested image, as UID/GID 1000. Record the image digest when deploying. Administer Docker only through the restricted host administrator. Set up directories on the host.

   ```bash
   sudo mountpoint -q /srv/electioncloud-kafka &&
     sudo install -d -o 1000 -g 1000 -m 0700 /srv/electioncloud-kafka/data
   sudo install -d -o 1000 -g 1000 -m 0700 /etc/electioncloud-kafka
   cd /opt/electioncloud/infra/aws
   sudo install -m 0600 .env.example .env
   sudoedit .env
   ```

   Set the actual private bind IP and DNS name in `.env`. Deliver `broker.p12`, `ca.pem`, `tls-password`, `admin-password`, `worker-password`, `publisher-password`, and `consumer-password` to `/etc/electioncloud-kafka` via the restricted secret workflow. Set files to UID/GID 1000 and mode 0600. The PKCS#12 contains the private key and server chain with the advertised DNS name in the certificate SAN. `ca.pem` contains the trusted CA chain. Password files contain independent random alphanumeric values of at least 24 characters with no other content. The bootstrap script initializes SCRAM only on an empty data volume. To rotate credentials on existing storage use Kafka's authenticated SCRAM administration, coordinate with Person 1, and update the staged secrets on the host. Never reformat a running election's storage.
4. Start and inspect the service. The broker/controller are colocated. KRaft uses a loopback-only controller socket and the authorizer permits its internal anonymous principal. The published client listener requires TLS and SCRAM. Kafka is a single point of failure in this setup.

   ```bash
   sudo install -m 0644 electioncloud-kafka.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now electioncloud-kafka
   sudo systemctl status electioncloud-kafka
   sudo journalctl -u electioncloud-kafka -n 50
   sudo docker compose ps
   sudo docker compose logs --tail 100 broker
   sudo docker compose exec -T broker bash /assets/grant-worker.sh '<verified-election-topic>' split
   ```

   Use `split` for separate Azure producer and consumer deployments, or `combined` for the baseline worker. Grant only the deployed mode. Use the exact topic and group from [the connection contract](CONTRACT.md). Any new election requires a deliberate new grant. Test over the Azure private route from the actual client runtime, first with a separate synthetic election ID and its matching topic ACL. Run the existing web/worker synthetic flow in README.md. Submit one ballot, verify durable receipt and accepted turnout of one, replay the same session and verify turnout stays one. Confirm logs show broker authentication and Kafka delivery without logging secrets, and repeat connectivity after a broker restart. Exercise the producer and consumer from their respective Azure runtimes when split. Review ACLs and check that an unapproved topic is denied.

## Primary tally host

1. Restrict access to the designated tally operator through Session Manager. Clone and detach at the reviewed release commit. Set up a virtual environment under that checkout with `python3 -m venv .venv` and `.venv/bin/python -m pip install -r requirements-cosmos.txt`. Use the Azure CLI installation approved for the Linux image. Ensure the AWS host reaches the Cosmos NoSQL endpoint using the approved route and private DNS. For a private endpoint use VPN routes and Azure forwarding for the endpoint's private DNS zone. Keep using the account HTTPS FQDN so TLS validates. Prefer Cosmos Gateway mode as used by the Python SDK and verify TCP 443.
2. Have the Azure administrator assign **Cosmos DB Built-in Data Reader** to the Entra tally principal at the demo container scope. The existing tally point-reads state and queries ballot documents. The role supplies metadata, item read, query and change feed actions. Cosmos permissions apply at container scope, while the code queries the chosen election partition. Use a dedicated demo container when the operator should only see that election's data. The designated Azure closure operator uses their existing contributor grant to run `python electioncloud.py close` after the worker drains the outbox. Keep closure authorization separate from AWS tally read access. [Cosmos data-plane permissions](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/reference-data-plane-security)
3. Sign in with the tally operator's Entra identity under the approved interactive flow. Keep the Azure CLI token cache in the operator's private home or private temporary session. Confirm closure using turnout before requesting the tally key.

   ```bash
   export ELECTIONCLOUD_STORAGE=cosmos COSMOS_AUTH=azure-cli
   export COSMOS_ENDPOINT='https://<account>.documents.azure.com:443/'
   export COSMOS_DATABASE='<database>' COSMOS_CONTAINER='<container>'
   export ELECTIONCLOUD_ELECTION_ID='<agreed-election-id>'
   az login --tenant '<tenant-id>' --allow-no-subscriptions
   .venv/bin/python electioncloud.py turnout
   ```

   Confirm `closed: true` and the authorized election ID. Obtain approval to read the specific matching key version from the designated secret store. Under the Key Vault option, grant secret Get to the designated operator at the specific secret scope and route the host to the vault. Use a temporary directory in operator-only RAM-backed storage. Keep the approved session audit settings and avoid sending secret material to the terminal or logs. Never print or paste the PEM.

   ```bash
   (
     set -e
     umask 077
     key_dir=$(mktemp -d /dev/shm/electioncloud.XXXXXXXX)
     trap 'rm -f -- "$key_dir/tally.pem"; rmdir -- "$key_dir"' EXIT
     az keyvault secret download --vault-name '<vault>' --name '<secret>' \
       --version '<approved-version>' --file "$key_dir/tally.pem" --only-show-errors
     # Create a new protected output file only after a successful tally.
     result=$(.venv/bin/python infra/aws/tally_result.py --private-key "$key_dir/tally.pem")
     set -o noclobber
     printf '%s\n' "$result" > result.json
   )
   ```

   Verify `totalCounted` equals closed turnout and the payload matches [the v1 fixture](result-fixture.json). On key error, review the approved secret reference and release. On count mismatch review Cosmos reachability and consistency, and retry. Keep the election closed and hold publication on any failure.
4. Once Persons 1 and 3 approve the destination and schema, publish using an authorized Entra publisher scoped to the private result container. Prefer create and read permissions constrained by the team's publishing controls. Use the same canonical blob for primary and fallback and enforce a conditional create on every publishing path. The agreed identifier must use lowercase alphanumeric characters and hyphens for this path. Azure's reader identity needs Blob Data Reader scoped to this container.

   ```bash
   [[ "$ELECTIONCLOUD_ELECTION_ID" =~ ^[a-z0-9-]+$ ]] &&
   az storage blob upload --auth-mode login --account-name '<storage-account>' \
     --container-name '<private-results-container>' \
     --name "${ELECTIONCLOUD_ELECTION_ID}.json" --file result.json \
     --content-type application/json --if-none-match '*' --overwrite false --only-show-errors
   ```

   On a conflict or ambiguous timeout, read the canonical blob and compare it with the approved aggregate. If it matches, record the existing publication. If it differs, escalate to the election owners and keep the accepted object in place. Capture the blob path, ETag, release commit, approved election ID, UTC time and operator audit reference. Sign out after the session.

## Monitoring, costs and cleanup

Give Person 4 the EC2 instance IDs and CloudWatch status checks, plus the broker and tally host log locations. For the broker monitor Kafka process/container state, an authenticated metadata check from the workload route, broker errors and EBS filesystem usage. Collect disk usage through the CloudWatch agent and use log retention. The systemd unit reports startup and shutdown. Inspect the actual container with `docker compose ps` and broker logs with `docker compose logs`. For the tally record invocation outcome, duration, storage errors and publication state in restricted operator logs. Share technical status without credentials, tokens, vote records, key material or partial results. Person 4 owns Lambda and alert routing.

Before approval estimate costs for both EC2 runtimes, encrypted EBS, snapshots, cross-cloud tunnel and transfer, DNS resolver endpoints, egress or interface endpoints, log ingestion and retention, Cosmos and result storage. After rehearsal stop services, revoke synthetic topic ACLs and credentials, revoke temporary access, and remove synthetic data and DNS rules according to the team retention policy. Request approval before deleting volumes, snapshots, network attachments or results. Confirm billable resources are released in both clouds and retain only approved evidence. [AWS Pricing Calculator](https://calculator.aws/)

## Reproduce local verification

Run these commands from the repository root on the separate PC with Docker Desktop and Python.

```powershell
python -X utf8 tests/integration/smoke_compose.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-kafka.txt -r requirements-cosmos.txt
.\.venv\Scripts\python.exe infra/aws/smoke_kafka.py
.\.venv\Scripts\python.exe infra/aws/test_tally.py
```

The secure smoke test uses loopback port 9094, a disposable certificate and generated credentials. Ensure the port is free. The mock tally test exercises production counting code while replacing the Cosmos transport. See [test evidence](VERIFICATION.md) for scope and results.
