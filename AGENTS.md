# OPERATION ZERO: agent rules

Product spec: operation_zero_product_requirements_document.md (repo root). Read it before any task.
Stack: FastAPI + PostgreSQL + Redis + Python workers, React 18 + TypeScript strict.
Baseline: tag v0.1.0-baseline (commit 2aca48d). 97 backend tests passing.

## Invariants (never weaken in any change)
1. Core monitoring and incidents work with AI off (OZ_AI_PROVIDER=none).
2. AI is read-only and evidence-grounded: 4-part output, uncited facts dropped, no numeric confidence, no autonomous remediation or shell execution.
3. Private network ranges are blocked by default on health checks (SSRF).
4. Strict workspace_id tenant scoping on every API and worker.
5. Secrets are redacted before persistence and before any external LLM call.
6. GitHub commits are context, not proof of root cause.
7. No mocked data in the UI. Unbuilt screens say so.

## Git workflow
- One work package = one branch = one PR. Branch from the latest main.
- Branch names: feat/, fix/, test/, ci/, docs/, chore/, ops/.
- Conventional Commits, small commits. Never rewrite history.
- Before a PR run: `ruff check app tests`, `ruff format --check app tests`, `python -m pytest` (do not add -q, pytest.ini already sets it), and `npm run build` in frontend. Paste real output.
- Open the PR with `gh pr create`. Body sections: Summary, PRD reference (section / OZ story / milestone), What changed, How to test, Screenshots (UI), Security and tenant-isolation impact, Risks and rollback, Invariants checklist.
- Wait for CI (`gh pr checks --watch`), fix failures on the same branch, then STOP and give me the PR link plus a 5-line summary.
- NEVER merge. NEVER push to main. NEVER force-push. NEVER skip hooks.
- After I merge: checkout main, pull, delete the merged branch locally and remotely.
- After every PR run `git fetch --all --prune && git status -sb && git branch -vv` and report anything not on GitHub.

## Honesty
- Never claim something passes unless you ran it and saw it pass.
- Never claim SOC 2, ISO 27001 or GDPR compliance.
- If the PRD and the code conflict, ask me. Do not silently change either.
- Ask me before deciding anything listed in PRD section 12 open questions.
- Do not run `npm audit fix --force` unless a package says so.

## Work packages (in order, one PR each)
1. ci/github-actions-pipeline: backend ruff + pytest with Postgres and Redis services, frontend tsc + build, pip-audit and npm audit, gitleaks, CodeQL, Docker build + Trivy, Dependabot, PR and issue templates, CODEOWNERS, SECURITY.md. Print the gh api commands for branch protection; I run them.
2. chore/frontend-dependency-upgrades: fix the npm audit findings (vite high/moderate, react-router-dom moderate, esbuild transitive). Needs breaking upgrades (vite 8, react-router 7). Fix the code, keep the build green, document changes.
3. docs/prd-conformance-audit: map the 10 MVP acceptance criteria, 16 entities and core API endpoints to code and tests in docs/PRD_CONFORMANCE.md (PASS/PARTIAL/MISSING with file references). Open one GitHub issue per gap.
4. fix/prd-backend-gaps: idempotency keys, webhook replay protection, token encryption at rest, cursor pagination, worker backoff + dead-letter, OpenAPI contract tests (split into several PRs if large).
5. feat/ui-log-explorer
6. feat/ui-alerts
7. feat/ui-incidents (detail, timeline, evidence, 7 states, AI panel with feedback)
8. feat/ui-integrations-deployments (GitHub scope review, test, revoke)
9. feat/ui-reports-audit-settings
10. feat/notification-centre-email (SMTP off by default, mail catcher in Compose)
11. feat/ui-overview-polish-a11y (WCAG 2.2 AA, timezone display)
12. test/e2e-playwright (PRD demo walkthrough)
13. test/security-suite (tenant isolation, privilege escalation, SSRF, injection, rate limits, secret exposure)
14. test/ai-eval-suite (citations, hallucination, prompt injection, permission boundary, provider outage)
15. test/load-k6
16. ops/runbooks-and-staging
17. docs/portfolio-pack (README, diagrams, ADRs, threat model, OpenAPI, postmortem)
18. feat/pilot-instrumentation (privacy-safe metrics from PRD section 10)
