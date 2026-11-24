# Codex brief for Oussama Benachour — Git, Lambda, monitoring and integration
Repository: [ZakariaBelouad/ElectionCloud](https://github.com/ZakariaBelouad/ElectionCloud)


### Clone on your PC

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git
cd ElectionCloud
git switch -c team/ops-integration
```

Run the clone commands once after the baseline is on main and your GitHub account has access.

I am Oussama Benachour, working from my own PC. I own team integration for ElectionCloud. Read TEAM-PLAN.md, README.md, and AZURE.md. Work on branch team/ops-integration. Keep alerting under infra/ops/, workflows under .github/workflows/ and cross-service tests under tests/integration/.

1. After Zakaria pushes the baseline to his repository and invites me, clone it on my PC. Review the tracked files and .gitignore for local databases, private keys, environment files, logs, and caches. Set up PR review and CI for Python checks, Docker build and the synthetic Compose flow. Leave cloud deployment behind explicit approval and cloud identities. Document how teammates clone and open their own branches.
2. Implement AWS Lambda technical alerts and administrator notifications with CloudWatch. Agree with Persons 1–3 on health signals and fallback routing to OCI Functions. Define a small event schema with event ID, service, severity, observation time and status. Exclude voter identifiers, vote choices, tokens and keys. Verify event deduplication and simulate notification failure with a test destination.
3. Build the release checklist and repeatable smoke test. Cover one-time session, Kafka queue and replay, durable receipt, turnout without candidate totals, close, AWS tally, dashboard publication, alert delivery and Oracle standby/fallback rehearsal. Keep local tests runnable on each machine and record the exact revision used in the shared demo.
4. Check that all required fiche services appear in the deployment inventory. Gather sanitized logs and test results from the owners, record anything still pending and prepare the final runbook. Use cloud monitoring for each provider and document the cleanup owner.

Ask before publishing a repository, sending real notifications, or provisioning billable resources. Open a PR with CI, Lambda and monitoring configuration, and the tested integration checklist.

## Work packets to execute on my PC

1. **Seed and onboard.** Review the clean baseline Zakaria prepares from his PC using the allowlist in TEAM-PLAN.md. Add ignore rules and inspect the staged diff. After Zakaria pushes the baseline and shares the repo, have each teammate record their clone path, branch, and baseline commit. Collect a one-line local test result from each teammate to verify onboarding. Each teammate owns their own credentials and Docker installation.
2. **Build PR checks.** Use a runner that checks out a clean copy of the repo. Build both Docker targets, validate Compose, and run a synthetic vote in a unique Compose project from start to finish. Add timeouts and clean up only the test project's resources. Ensure the workflow requires neither a teammate's running PC nor cloud credentials. Document local equivalents for every check.
3. **Implement alert routing.** Put AWS Lambda and CloudWatch configuration in infra/ops/. Start with fixtures for worker unhealthy, Kafka unavailable, Cosmos write failures, and recovery. Implement and test notification deduplication. Coordinate the fallback event and invocation with Person 3. Verify logs and alerts contain technical status only. Use a mock sender locally and an authorized test destination for cloud verification.
4. **Coordinate the shared demo.** Track owner, interface, latest tested commit and deployment status in the integration checklist. Agree a release tag and fresh shared election ID. Run the rehearsal in order: authenticated staff session, cast, pending or accepted receipt, retry/replay, turnout, close, primary tally and publication, recovery and alert fallback. Record one expected and observed result per check. Collect evidence from each cloud owner.
5. **Release handoff.** Publish the release checklist and cleanup instructions in the PR. List repeatable local tests, cloud tests, and blockers by owner. Keep credentials and private operator material out of CI logs and the repo.

Acceptance checks on my PC: a clean clone can reproduce CI with only public dependencies and synthetic data, test resources are isolated by project, and repeated alerts are demonstrated with a mock sender.
