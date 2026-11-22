# AWS and Azure handoff

Proposed for Person 1 and Person 3 review. The broker address and CA below are placeholders until deployment.

## Kafka

| Item | Value |
| --- | --- |
| Bootstrap and advertised address | `kafka.aws.example.internal:9094` via private DNS and routing |
| Transport | `SASL_SSL` with hostname verification and `SCRAM-SHA-512` |
| Client trust | PEM CA chain at a readable path in each Azure runtime, or the runtime CA bundle when it already trusts the issuer |
| Client identity | `election-worker` for the baseline `both` mode, or `election-publisher` and `election-consumer` for the split Azure runtime. Keep SCRAM credentials in Key Vault-backed application secrets |
| Topic | `electioncloud-` plus the first 32 lowercase hex digits of SHA-256 over the exact stored public PEM bytes, including its final newline |
| Consumer group | Exact topic plus `-sqlite`, including when Cosmos is the backend |
| Partition and replication | One partition, replication factor one in the demo |
| Key and value | 32-character ASCII technical ballot ID and raw encrypted ballot bytes |
| ACL | Literal topic Create, Describe and Write for the publisher. Literal topic Describe and Read and literal group Read for the consumer. Combined mode grants their union. No wildcard or prefix grant |
| Delivery | Idempotent publisher. Worker stores the matching outbox submission before committing the offset. Duplicate deliveries do not add ballots |

Set `ELECTIONCLOUD_BROKER`, `ELECTIONCLOUD_KAFKA_SECURITY_PROTOCOL=SASL_SSL`, `ELECTIONCLOUD_KAFKA_SASL_MECHANISM=SCRAM-SHA-512`, `ELECTIONCLOUD_KAFKA_USERNAME`, `ELECTIONCLOUD_KAFKA_PASSWORD`, and when needed `ELECTIONCLOUD_KAFKA_CA_PATH`. Person 1 should confirm certificate mounting and the settings in the actual Azure image. The proposed split matches the Azure branch runtime roles. Confirm the exact-topic scope and final secret references during review. The current publisher calls CreateTopics at startup even for an existing topic. Grant Azure clients only the configured topic and corresponding group.

Send Person 1 the deployed FQDN and port, CA chain or issuer and fingerprint, approved Azure subnet source ranges, principal and exact ACL resources. Supply the secret reference separately. Broker service logs are available from Docker and the systemd journal as described in the runbook.

## Aggregate result

The draft v1 schema uses JSON and the existing tally mapping. See [one-vote fixture](result-fixture.json). `electionId` is the exact Cosmos partition identifier, `schemaVersion` is the integer 1, `candidateTotals` maps exact candidate display names to nonnegative integer counts including zeros, and `totalCounted` is their sum. Agree on this schema and the Azure destination with Persons 1 and 3 before integration. Both tally roles must use the same election ID and publication destination.

Proposed publication is a private Azure Blob container with one canonical object per election and a conditional create. Azure can read that object by election ID after closure. Share only this aggregate, through the authorised publication workflow in the runbook.
