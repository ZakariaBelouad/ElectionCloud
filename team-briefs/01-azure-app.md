# Codex brief for Zakaria Belouad — Azure app and deployment
Repository: [ZakariaBelouad/ElectionCloud](https://github.com/ZakariaBelouad/ElectionCloud)


### Clone on your PC

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git
cd ElectionCloud
git switch -c team/azure-app
```

Run the clone commands once after the baseline is on main and your GitHub account has access.

If main is still empty, use the first-push checklist in TEAM-PLAN.md from your clean staging copy before cloning.

I am Zakaria Belouad, working from my own PC. I own the Azure track for ElectionCloud. Read TEAM-PLAN.md, README.md, and AZURE.md in this clone. Work on branch team/azure-app. Start with the existing Python web app, Cosmos backend, Kafka worker, and deployment script. Coordinate shared runtime and contract changes with the other tracks.

1. The GitHub repository has been created. Push the reviewed baseline if main is still empty from my PC using the first-push checklist in TEAM-PLAN.md. Invite the other three teammates, then switch to team/azure-app. Reproduce the local baseline. Move the outbox publishing loop to an App Service-owned process or component, keeping durable retries. Keep Kafka consumption and the final ballot write in Azure Container Apps. Preserve the Kafka key and encrypted value contract. Confirm the browser waits for the durable receipt and the worker can replay a message without incrementing turnout twice.
2. Implement or finish the staff and dashboard flows. Enforce Entra staff role checks in the hosted app for session issuance and administration. Show turnout before closure and show approved tally results only after closure. Agree with Person 2 on the results format and publication interface. Keep the tally key outside web and worker containers.
3. Prepare Azure App Service, Container Apps, Cosmos DB, Entra, App Gateway/WAF, Key Vault and Azure Monitor configuration. Reuse deployment code. Document permissions, health probes, private connectivity to Kafka, and the Cosmos layout. The prototype currently uses one logical partition with distinct document types. Document any remaining identity and ballot isolation limitations explicitly.
4. Add tests for staff authorization, duplicate sessions, delayed receipt, duplicate delivery and post-close result visibility. Run local Compose/emulator checks. With authorized cloud access, verify a synthetic vote end to end and record the exact tag and what remains unverified.

Coordinate with Person 2 on broker endpoint, TLS and tally publication, Person 3 on recovery access, and Person 4 on telemetry and release checks. Avoid committing real credentials, tokens, databases or keys. Ask for cloud resource authorization before provisioning. Open a PR with changes, setup instructions, and test evidence.

## Work packets to execute on my PC

1. **Baseline and interfaces.** Follow the separate-PC setup in TEAM-PLAN.md on my own clone. Record the initial commit SHA and a successful ballot receipt. Inspect `web.py`, `kafka_worker.py`, and `cosmos_store.py`. Write a short interface note for the team covering the app/worker environment settings, health endpoint, topic naming, and result publication. Confirm the current Kafka message shape with Person 2 before changing anything.
2. **Split the Kafka responsibilities.** Keep session consumption and the outbox write atomic in Cosmos. Add a publisher loop owned by the App Service deployment that reads the durable outbox and publishes encrypted records. Run the publisher and consumer as separate processes locally before making Azure changes. Remove the publish loop from the consumer path once the new publisher is wired in. Handle broker downtime by retaining outbox entries and retrying on recovery. Only the consumer may move a matching entry into the ballot box and acknowledge the offset. Provide separate log messages for publish and durable store.
3. **Complete the web flow.** Separate session issuance from ballot casting in the route and authorization logic. Validate hosted staff permissions at the action and route level. Keep the single-machine demo runnable with synthetic fixtures. Add tests for unauthorized staff operations, duplicate issuance, pending receipts, accepted receipt lookup, closed voting, and dashboard results visibility. Define result import/publication with Person 2 and prevent duplicate publication.
4. **Azure staging.** Configure the App Service and publisher lifecycle, Container Apps consumer, Cosmos partition, Entra sign-in, Key Vault references, App Gateway/WAF and Azure Monitor in the documented deployment order. Verify the application and publisher can reach the broker from Azure before casting the test ballot. Conference with Person 2 if DNS, TLS trust, or ACL checks fail. Test hosted route restrictions and document any unprovisioned service.
5. **Handoff.** Publish a setup note containing Azure resource names, nonsecret hostnames, settings names, the test election ID and exact image tag. Include commands to show turnout, inspect app/worker logs, and verify post-close result publication. Give Person 4 a redacted test transcript.

Acceptance checks on my PC: kill the publisher while a ballot is queued, restart it, and obtain one durable receipt with turnout increasing once. Repeat with the consumer stopped. Verify turnout and tally publication rules before and after close.
