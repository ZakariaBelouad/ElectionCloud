# Codex brief for Mohammed Reda Zelmati — AWS Kafka and primary tally
Repository: [ZakariaBelouad/ElectionCloud](https://github.com/ZakariaBelouad/ElectionCloud)


### Clone on your PC

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git
cd ElectionCloud
git switch -c team/aws-kafka-tally
```

Run the clone commands once after the baseline is on main and your GitHub account has access.

I am Mohammed Reda Zelmati, working from my own PC. I own the AWS EC2 track for ElectionCloud. Read TEAM-PLAN.md, README.md, AZURE.md, kafka_worker.py, and the existing tally command. Work on branch team/aws-kafka-tally and keep infrastructure files under infra/aws/. Person 4 owns Lambda and alert routing.

1. Create reproducible setup for Apache Kafka on one dedicated EC2 VM. Specify persistent broker storage, KRaft configuration, private cross-cloud reachability from the authorized Azure services, correct advertised DNS, SASL_SSL with SCRAM, certificate trust and least-privilege Kafka ACLs. Keep public plaintext listeners disabled. Prove connectivity with a synthetic producer/consumer test. Provide the endpoint and trust requirements to Person 1 via the agreed handoff.
2. Prepare a separate EC2 VM for the primary tally. Reuse the ElectionCloud tally logic. Document how the authorized tally operator reaches Cosmos, obtains the tally key through a restricted workflow and runs the count only after closure. Never put the key in an image or repository. Agree with Persons 1 and 3 on a results contract that includes election ID, schema version, candidate totals and total counted. Document how an authorized operator publishes one result for an election.
3. Validate one-vote counting from synthetic fixtures, wrong-key rejection, and rejection before closure. Document the validated Kafka and Cosmos permissions, what the VM monitors expose to Person 4, resource costs to check and cleanup steps. Test with local tooling where possible and distinguish EC2 checks that require access.

Ask before creating billable resources. Do not change shared runtime files without coordinating with Person 1. Open a PR with the AWS deployment assets, operator runbook and test evidence.

## Work packets to execute on my PC

1. **Baseline and contract.** Clone and run the separate-PC demo. Record the Kafka contract with Person 1. The current key is a 32-character technical ballot ID and the value is encrypted ballot bytes. Topic names use `electioncloud-` followed by the first 32 hexadecimal characters of the SHA-256 of the election public PEM. Verify these against the checked-out code. Write the approved connection and topic contract under infra/aws/ using placeholders for all credentials.
2. **Kafka VM assets.** Write broker setup and service startup files that a teammate can run on a fresh EC2 Linux VM. Include Java/Kafka version, service user, log storage path, listeners and broker address, DNS/TLS, private network rules, principal setup and scoped ACLs. If separating producer and consumer credentials, coordinate the new settings with Person 1. Test Kafka locally using Docker and synthetic messages. Record exact commands for broker startup, status, logging, and a connectivity smoke test.
3. **Tally VM assets.** Provide a separate VM setup and operator commands to retrieve the correct revision, install dependencies, access Cosmos, close or confirm closure through the agreed admin workflow, and run the existing tally code. Establish how to hand only the approved aggregate result to Azure. Verify the output matches the schema Person 1 and Person 3 will implement. Test the tally locally with a synthetic election, including missing/wrong key and before-close cases.
4. **Cloud integration.** Once EC2 access is approved, deploy both VMs separately. Use the separate VM console or SSH from my own PC, and have Person 1 test from the actual Azure runtime network. Share the broker DNS and port, certificate trust, ACL scope, and log locations. Keep the broker private. Leave key access with the designated operator.
5. **Handoff.** Deliver an AWS runbook with two distinct host roles, a reproducible synthetic test, and expected health signals for Person 4. Hand Person 3 the tally invocation and result fixture. Label mocked, local, and cloud verification separately.

Acceptance checks on my PC: broker restart preserves its configured log storage in the test setup, the authorized test connection can produce and consume, and the tally matches the synthetic fixture with zero results available before closure.
