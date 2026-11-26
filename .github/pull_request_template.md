## Summary
<!-- What does this PR do, in 2-3 sentences? -->

## PRD reference
<!-- Section / OZ story / milestone, e.g. section 11a, milestone M2. -->
- PRD section:
- Milestone:
- Issue:

## What changed
-

## How to test
<!-- Exact commands and expected result. Paste real output where useful. -->
```bash
cd backend
ruff check app tests
ruff format --check app tests
python -m pytest
cd ../frontend
npm run build
```

## Screenshots (UI)
<!-- Required for UI changes. Write "Not applicable" for non-UI changes. -->

## Security and tenant-isolation impact
<!-- workspace_id scoping, RBAC, redaction, SSRF, secrets, AI guardrails. -->
- [ ] No change to tenant scoping
- [ ] No new external network calls
- [ ] No secrets or sensitive fields added to logs or persistence

## Risks and rollback
<!-- What can break? How do we revert? -->

## Invariants checklist
- [ ] Core monitoring and incidents work with AI off
- [ ] AI is read-only and evidence-grounded
- [ ] Private network ranges blocked by default on health checks
- [ ] Strict workspace_id tenant scoping
- [ ] Secrets redacted before persistence and before external LLM calls
- [ ] GitHub commits presented as context, not proof
- [ ] No mocked UI data; unbuilt screens say so
