# AGENTS.md

Follow the collaboration and review rules in README.md. Changes reach `main`
through a PR with a GitHub approval from a team member other than the author.
An AI review or a general deployment request does not replace that approval.
Preserve unrelated, uncommitted work and never commit credentials or local DBs.

## Testing

- Backend: in `src/backend`, run `uv run --locked ruff check app tests`,
  `uv run --locked ruff format --check app tests`, and
  `RUN_DB_TESTS=1 uv run --locked pytest -q` against a test PostgreSQL database.
- Deployment helpers: from the root, run
  `uv run --project src/backend --locked pytest -q deploy/test_*.py`.
- Deployment integration: see `deploy/README.md`; run only against a fresh,
  disposable Compose project. Never target a shared or production database.

## Deploy Configuration (configured by /setup-deploy)

- Platform: GitHub Actions + enterprise Ubuntu Docker Compose
- Production URL: http://127.0.0.1:18081 (server loopback; no public URL configured)
- Deploy workflow: .github/workflows/backend-ci.yml
- Deploy status command: `gh run list --repo dlwlssud123/SoftwareProject --workflow backend-ci.yml --branch main --limit 3 --json headSha,status,conclusion`
- Merge method: squash, after the required team approval
- Project type: API
- Post-deploy health check: on the server, `curl --fail http://127.0.0.1:18081/api/v1/health/ready`

### Custom deploy hooks

- Pre-merge: successful `checks` job (Ruff, real PostgreSQL tests, image build, deployment and rollback integration)
- Deploy trigger: automatic on relevant backend/deployment changes to main, only when repository variable `VALUEFLOW_CD_ENABLED=true`; `workflow_dispatch` on main can redeploy
- Deploy status: `gh run list --repo dlwlssud123/SoftwareProject --workflow backend-ci.yml --branch main --limit 3 --json headSha,status,conclusion`
- Health check: on the server, `curl --fail http://127.0.0.1:18081/api/v1/health/ready`

Target: `kapje90@210.90.113.81:1190`, directory
`/home/kapje90/Documents/ValueFlow`, Compose project `valueflow-server`.
Use the dedicated deployment SSH key, strict host-key checking, a DB backup,
and the shared deployment/import lock. Do not alter other server projects.
On API failure restore the previous API image; do not automatically downgrade
or restore the database. Keep the backup for an explicit recovery decision.

Activation requires the workflow to be merged, `checks` and `publish` to pass,
and SSH health verification with the dedicated key. GitHub Secrets are in the
`development` environment; server `.env` stays on the server. Check actual
GitHub settings and Actions results before claiming automatic deployment works.
