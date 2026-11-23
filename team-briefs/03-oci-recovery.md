# Codex brief for Saad Mesbah — Oracle Cloud recovery
Repository: [ZakariaBelouad/ElectionCloud](https://github.com/ZakariaBelouad/ElectionCloud)


### Clone on your PC

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git
cd ElectionCloud
git switch -c team/oci-recovery
```

Run the clone commands once after the baseline is on main and your GitHub account has access.

I am Saad Mesbah, working from my own PC. I own the Oracle Cloud track for ElectionCloud. Read TEAM-PLAN.md and the existing tally code. Work on branch team/oci-recovery and keep files under infra/oci/. Coordinate with Persons 1 and 2 on access and the result schema and with Person 4 on alert routing.

1. Create reproducible OCI Compute standby setup for the same tally revision used on EC2. Define how standby reaches the authoritative closed-election data, or how a documented verified snapshot is synchronized if direct access is unavailable. State the readiness checks, data freshness requirements and expected demo recovery time. Keep the tally key in a restricted operator or secret workflow.
2. Implement the OCI Functions supplemental health checks and fallback notifications using synthetic fixtures. Process technical status only. Repeated event IDs should not produce duplicate notifications. Document invocation, identity, retry and monitoring configuration.
3. Write a manual failover runbook. Verify that the election is closed, confirm primary failure, authorize a standby operator, compute and compare totals, publish through the agreed guard against duplicate publication, then document failback. Do not claim automatic failover if it has not been implemented and tested.
4. Run a local recovery rehearsal from a synthetic closed election and test notification failures and replays. With authorized OCI access, deploy the standby VM and functions and capture evidence that the recovery process works.

Ask before provisioning billable services. Share reviewed code and placeholder configuration only. Open a PR with setup, failover instructions, tests, and remaining deployment prerequisites.

## Work packets to execute on my PC

1. **Lock the recovery input.** Clone the repo and reproduce the baseline. Request the tally command, release tag, and result fixture from Person 2. Ask Person 1 to identify the authoritative closed-election data and approved publication interface. Use a synthetic fixture or local Cosmos emulator on my own PC while the cloud path is pending.
2. **Build the standby setup.** Under infra/oci/, document VM image, service account, network route, tenancy, compartment and region placeholders, and software initialization. Pin the standby to the same app revision used by the EC2 tally. Add checks for data availability, election closure, current revision and tally-key access before failover. If snapshots are required, document export, validation, freshness, retention and recovery limits.
3. **Implement the functions.** Create the supplemental check and fallback notification handlers. Add fixture-based local tests for invalid events, repeated event IDs, notification-provider errors, and retry behavior. Log service status and event IDs. Work with Person 4 on the triggering signal, idempotency store, and test destination.
4. **Run a switching exercise.** Simulate primary unavailability. Run the standby tally for a closed synthetic election and compare its totals to Person 2's fixture. Verify the handoff guard stops a second publication for the same election. Record recovery time and document how to return control to the primary.
5. **Handoff.** Give Person 4 the fallback function trigger, event fixture and Monitoring signal. Give Person 1 the standby result format and publication guard. In the PR, show exactly which checks run on my PC and which need OCI, Cosmos, or cross-cloud network access.

Acceptance checks on my PC: repeated health events cause one notification in the fixture test, and the standby tally exactly matches the primary result for the same closed-election fixture.
