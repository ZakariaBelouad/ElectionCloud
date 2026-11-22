# Verification evidence

Baseline `c203aaa02b27cdfae8da1ab40613e1fb37ca01f4`. Local Windows PC, Python 3.14.10, Docker Engine 29.9.3 and Compose 5.7.0. Broker image `apache/kafka:4.4.0` resolved to `sha256:833b867a9585a141da455dc2b57431c65cbccb27f11c91f694444cca9f777e0f`, with Java Temurin 25.0.4.1.

| Scope | Command | Observed |
| --- | --- | --- |
| Local baseline | `python -X utf8 tests/integration/smoke_compose.py` | 11/11 passed. Durable Kafka receipt, replays leave turnout unchanged, no totals before closure, and closed tally yields 2 and 1 for the three synthetic ballots. |
| Local secure broker | `python infra/aws/smoke_kafka.py` | TLS and SCRAM authenticated separate publisher and consumer accounts. The publisher created the allowed topic and produced idempotently, but creation outside the topic scope was denied. The consumer could read the synthetic record and could not create the topic. Container replacement using the same data directory preserved KRaft metadata, ACLs and the record. |
| Mocked Cosmos transport | `python infra/aws/test_tally.py` | 4/4 passed against the real Cosmos tally code. The exact public PEM hashes to the expected topic. One ciphertext yields counts 1 and 0. Missing and wrong keys fail. A tally before closure fails before querying ballots. The expected aggregate matches the result fixture. |
| Local repository check | `python tests/integration/check_repo_hygiene.py` | Passed. |

## Pending cloud checks

- Person 2 confirms boot, EBS remount and replacement on approved EC2, the private DNS answer, the issued certificate chain, and broker and tally health signals.
- Persons 1 and 2 test TLS, SCRAM, topic grants and a synthetic ballot from the actual App Service and Container Apps networks. They confirm the exact Kafka ACLs and hand off the deployed DNS name and CA information.
- Persons 1 and 2 verify from the tally VM that the scoped Cosmos reader can query ballots and is denied writes, that only the designated operator can fetch the key, and that the closed count matches the synthetic run.
- Persons 1 through 3 approve the aggregate schema and publication destination, then verify that competing primary and fallback submissions leave one canonical object. Person 4 reviews monitored status signals.
