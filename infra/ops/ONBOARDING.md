# Onboarding and Git workflow

## Check the baseline

The baseline on `main` was reviewed on this branch: 20 tracked files, no databases, keys, env files or logs. `.gitignore` already excludes `*.db`, `*.db-*`, `*.pem`, `*.key`, `.env*`, `*.log` and `__pycache__/`. CI runs `tests/integration/check_repo_hygiene.py` on every PR, so a leaked key or database fails the build.

## Each teammate, once

```powershell
git clone https://github.com/ZakariaBelouad/ElectionCloud.git
cd ElectionCloud
git switch -c <assigned-branch>
docker compose -p ec-local build web worker
docker compose -p ec-local run --rm --no-deps admin init --private-key /keys/tally.pem "Candidate A" "Candidate B"
docker compose -p ec-local up -d --wait
python tests/integration/smoke_compose.py
```

Branches: `team/azure-app`, `team/aws-kafka-tally`, `team/oci-recovery`, `team/ops-integration`.

## Daily flow

```powershell
git fetch origin
git merge origin/main
git add <your files only>
git commit -m "Short description"
git push -u origin <your-branch>
```

Then open a PR. The template asks for the tested commit, the commands run, expected against observed, and what still needs a cloud account. Ask the teammate who consumes your interface to review.

Never commit databases, keys, tokens, real `.env` files, logs, or screenshots that show session tokens.

## Settings only the repository owner can apply (Zakaria)

On `main`, under Settings, Branches, add a rule:

- Require a pull request with at least 1 approval
- Require status checks: `Python checks` and `Docker build and synthetic vote`
- Require branches to be up to date before merging
- Block force pushes and deletions

Also: confirm the repository visibility is what the team wants (it is public at the moment), and fill in the real handles in `.github/CODEOWNERS` before turning on code owner review.

## Onboarding record

Each teammate fills in one row in their first PR, or Oussama fills it in from their message.

| Teammate | Clone path | Branch | Baseline commit | Local test result (one line) |
| --- | --- | --- | --- | --- |
| Zakaria Belouad | | `team/azure-app` | | |
| Mohammed Reda Zelmati | | `team/aws-kafka-tally` | | |
| Saad Mesbah | | `team/oci-recovery` | | |
| Oussama Benachour | | `team/ops-integration` | `3cef265` | |
