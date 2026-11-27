# OPERATION ZERO — PRD Conformance Audit

- **Audit date:** 2026-11-27
- **Base commit:** `f18a928` (`chore(deps): bump nginx in /frontend (#4)`)
- **PRD:** `operation_zero_product_requirements_document.md` (repo root)
- **Scope:** the 10 MVP acceptance criteria, the 16 core entities and the core API surface in PRD §6 and §9, checked against the backend, tests, frontend routes and CI.
- **This document is read-only evidence.** It does not change application code.

## How to read the statuses

| Status | Meaning |
| :--- | :--- |
| **PASS** | The stated requirement has a code path and at least one automated test, unless the evidence column explicitly says “code path; no direct test”. |
| **PARTIAL** | The backend code path and tests exist, but a stated part of the requirement is missing (usually the user-facing screen or a real-infrastructure test). |
| **MISSING** | No code path, or no test and no reachable path. |
| **POST-MVP** | Explicitly outside the MVP in the PRD; not counted as a gap. |

A PASS is never based on a README claim or a planned screen. Where a frontend screen is absent, the criterion is marked PARTIAL even if the API is complete.

## Summary

| Area | PASS | PARTIAL | MISSING | POST-MVP |
| :--- | :---: | :---: | :---: | :---: |
| 10 MVP acceptance criteria | 7 | 3 | 0 | 0 |
| 16 core entities | 16 | 0 | 0 | 0 |
| 18 core API endpoints | 18 | 0 | 0 | 0 |
| Frontend views | 4 | 0 | 9 | 1 |
| Gap register | — | 8 | 7 | 1 open decision |

**Overall:** the backend MVP is substantially implemented and tested. The largest conformance gap is the user-facing control room: 9 of 14 MVP views are `PlannedPage` or absent. The second gap is test realism: the suite still runs on SQLite and does not exercise Redis rate limiting.

---

## 1. MVP acceptance criteria

Source: PRD §6 “Definition of done”. Each criterion below is the exact wording from the PRD.

| # | Criterion | Status | Code evidence | Test evidence | Gap / notes |
| :---: | :--- | :---: | :--- | :--- | :--- |
| 1 | Workspace/RBAC creation | **PASS** | `backend/app/api/v1/auth.py:61`; `backend/app/api/v1/workspaces.py:70,217,275`; `backend/app/core/permissions.py:15,46` | `backend/tests/test_auth.py:8`; `backend/tests/test_tenancy_rbac.py:49,61,72,88` | Member-management UI is missing; tracked as G5. |
| 2 | Service registration & pass/fail health checks | **PASS** | `backend/app/api/v1/services.py:72`; `backend/app/services/healthcheck.py:23,40` | `backend/tests/test_services.py:23,99,143` | Service detail/history UI is missing; tracked as G6. |
| 3 | Authenticated structured log ingestion rejecting invalid/unauthorized payloads | **PASS** | `backend/app/api/v1/logs.py:46`; `backend/app/services/redaction.py:134` | `backend/tests/test_logs.py:18,51,62,103,124,142` | Log explorer UI is missing; tracked as G3. |
| 4 | Alert rule firing on threshold breach | **PASS** | `backend/app/api/v1/alerts.py:105`; `backend/app/services/alerts.py:60,134` | `backend/tests/test_alerts.py:82,99,109,199,260` | Alerts UI is missing; tracked as G4. |
| 5 | Alert-to-incident conversion with ownership and status updates | **PASS** | `backend/app/api/v1/alerts.py:335`; `backend/app/services/incidents.py:63,127,193` | `backend/tests/test_alerts.py:171`; `backend/tests/test_incidents.py:31,80` | Incident UI is missing; tracked as G1. |
| 6 | Full incident timeline & linked evidence | **PARTIAL** | `backend/app/services/incidents.py:36,258`; `backend/app/api/v1/incidents.py:310,330` | `backend/tests/test_incidents.py:19,31,93,107,145` | Backend timeline/evidence is complete and tested. Incident detail UI is absent, so the user cannot inspect the full timeline. **G1.** |
| 7 | Verified GitHub webhooks visible as context | **PARTIAL** | `backend/app/services/github.py:234,263,306`; `backend/app/api/v1/webhooks.py:29`; `backend/app/api/v1/integrations.py:171` | `backend/tests/test_integrations.py:125,152,186` | Signature/replay/dedupe and storage are tested. “Visible as context” requires the deployments/integrations UI, which is absent. **G2.** |
| 8 | Evidence-cited AI summary clearly separating hypotheses | **PARTIAL** | `backend/app/services/ai/orchestrator.py:43,50,112`; `backend/app/services/ai/evidence.py:34`; `backend/app/services/ai/prompts.py:93` | `backend/tests/test_ai.py:36,71,103,130,152,179,197,211` | 4-part output, citation dropping and injection handling are tested. The incident AI panel/feedback UI is absent. **G1.** |
| 9 | Strict cross-workspace isolation | **PASS** | Tenant filters in `backend/app/api/deps.py` and the query layer; `backend/app/core/permissions.py` | `backend/tests/test_tenancy_rbac.py:8,29,72`; `backend/tests/test_incidents.py:241`; `backend/tests/test_ai.py:211` | Server-side 404 isolation and RBAC are tested. No cross-tenant UI path exists. |
| 10 | Audit logging of sensitive actions | **PASS** | `backend/app/services/audit.py:15`; calls from incident, integration, AI and workspace services | `backend/tests/test_incidents.py:26,198`; `backend/tests/test_integrations.py:103`; `backend/tests/test_tenancy_rbac.py:72`; `backend/tests/test_ai.py:67` | Audit query UI is missing; tracked as G5. |

---

## 2. Core entities (16)

Source: PRD §9 “Initial Data Model (16 core entities)”.

| # | Entity | Status | Model | Test evidence |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `User` | **PASS** | `backend/app/models/identity.py:33` (`users`) | `backend/tests/test_auth.py` |
| 2 | `Workspace` | **PASS** | `backend/app/models/identity.py:51` (`workspaces`) | `backend/tests/test_auth.py`, `backend/tests/test_tenancy_rbac.py` |
| 3 | `Membership` | **PASS** | `backend/app/models/identity.py:70` (`memberships`) | `backend/tests/test_tenancy_rbac.py` |
| 4 | `Service` | **PASS** | `backend/app/models/service.py:48` (`services`) | `backend/tests/test_services.py` |
| 5 | `HealthCheck` | **PASS** | `backend/app/models/service.py:83` (`health_checks`) | `backend/tests/test_services.py` |
| 6 | `HealthCheckResult` | **PASS** | `backend/app/models/service.py:107` (`health_check_results`) | `backend/tests/test_services.py:99`, `backend/tests/test_worker.py` |
| 7 | `LogEvent` | **PASS** | `backend/app/models/telemetry.py:33` (`log_events`) | `backend/tests/test_logs.py` |
| 8 | `AlertRule` | **PASS** | `backend/app/models/alerting.py:58` (`alert_rules`) | `backend/tests/test_alerts.py` |
| 9 | `Alert` | **PASS** | `backend/app/models/alerting.py:88` (`alerts`) | `backend/tests/test_alerts.py` |
| 10 | `Incident` | **PASS** | `backend/app/models/incident.py:73` (`incidents`) | `backend/tests/test_incidents.py` |
| 11 | `IncidentEvent` | **PASS** | `backend/app/models/incident.py:110` (`incident_events`) | `backend/tests/test_incidents.py` |
| 12 | `EvidenceLink` | **PASS** | `backend/app/models/incident.py:134` (`evidence_links`) | `backend/tests/test_incidents.py:107,145` |
| 13 | `Integration` | **PASS** | `backend/app/models/integration.py:44` (`integrations`) | `backend/tests/test_integrations.py` |
| 14 | `WebhookEvent` | **PASS** | `backend/app/models/integration.py:79` (`webhook_events`) | `backend/tests/test_integrations.py:152,186` |
| 15 | `AuditEvent` | **PASS** | `backend/app/models/audit.py:15` (`audit_events`) | `backend/tests/test_incidents.py:26,198`, `backend/tests/test_integrations.py:103`, `backend/tests/test_tenancy_rbac.py:72` |
| 16 | `AIAnalysis` | **PASS** | `backend/app/models/ai.py:27` (`ai_analyses`) | `backend/tests/test_ai.py` |

Supporting tables outside the PRD’s 16: `Notification` (`backend/app/models/platform.py:31`), `IdempotencyKey` (`:56`), `Report` (`:72`). These are implementation support, not missing entities.

---

## 3. Core API endpoints

Source: PRD §9 “Core API surface”. The implemented API is workspace-scoped (`/api/v1/workspaces/{workspace_id}/...`), which is an accepted implementation detail for tenant isolation. `POST /ingest/logs` and `POST /webhooks/github` are global and authenticated by ingestion key/signature respectively.

| # | PRD endpoint | Implemented path | Status | Handler | Test evidence |
| :---: | :--- | :--- | :---: | :--- | :--- |
| 1 | `POST /workspaces` | `/api/v1/workspaces` | **PASS** | `backend/app/api/v1/workspaces.py:70` | Registration flow `backend/tests/test_auth.py:8`; direct route not separately tested |
| 2 | `GET /workspaces/{id}` | `/api/v1/workspaces/{workspace_id}` | **PASS** | `backend/app/api/v1/workspaces.py:121` | Code path; no direct test |
| 3 | `POST /services` | `/api/v1/workspaces/{workspace_id}/services` | **PASS** | `backend/app/api/v1/services.py:72` | `backend/tests/test_services.py:23` |
| 4 | `GET /services` | `/api/v1/workspaces/{workspace_id}/services` | **PASS** | `backend/app/api/v1/services.py:143` | `backend/tests/test_services.py:23` |
| 5 | `GET /services/{id}/health` | `/api/v1/workspaces/{workspace_id}/services/{service_id}/health` | **PASS** | `backend/app/api/v1/services.py:376` | `backend/tests/test_services.py:99` |
| 6 | `POST /ingest/logs` | `/api/v1/ingest/logs` | **PASS** | `backend/app/api/v1/logs.py:46` | `backend/tests/test_logs.py:18,51` |
| 7 | `GET /logs` | `/api/v1/workspaces/{workspace_id}/logs` | **PASS** | `backend/app/api/v1/logs.py:150` | `backend/tests/test_logs.py:18,158` |
| 8 | `POST /alert-rules` | `/api/v1/workspaces/{workspace_id}/alert-rules` | **PASS** | `backend/app/api/v1/alerts.py:105` | `backend/tests/test_alerts.py:82,109` |
| 9 | `GET /alerts` | `/api/v1/workspaces/{workspace_id}/alerts` | **PASS** | `backend/app/api/v1/alerts.py:218` | `backend/tests/test_alerts.py:109` |
| 10 | `POST /alerts/{id}/acknowledge` | `/api/v1/workspaces/{workspace_id}/alerts/{alert_id}/acknowledge` | **PASS** | `backend/app/api/v1/alerts.py:252` | `backend/tests/test_alerts.py:143` |
| 11 | `POST /incidents` | `/api/v1/workspaces/{workspace_id}/incidents` | **PASS** | `backend/app/api/v1/incidents.py:148` | `backend/tests/test_incidents.py:19` |
| 12 | `GET /incidents/{id}` | `/api/v1/workspaces/{workspace_id}/incidents/{incident_id}` | **PASS** | `backend/app/api/v1/incidents.py:223` | `backend/tests/test_incidents.py:31` |
| 13 | `PATCH /incidents/{id}` | `/api/v1/workspaces/{workspace_id}/incidents/{incident_id}` | **PASS** | `backend/app/api/v1/incidents.py:232` | `backend/tests/test_incidents.py:31,249` |
| 14 | `POST /incidents/{id}/evidence` | `/api/v1/workspaces/{workspace_id}/incidents/{incident_id}/evidence` | **PASS** | `backend/app/api/v1/incidents.py:330` | `backend/tests/test_incidents.py:107` |
| 15 | `POST /incidents/{id}/ai-analysis` | `/api/v1/workspaces/{workspace_id}/incidents/{incident_id}/ai-analysis` | **PASS** | `backend/app/api/v1/incidents.py:372` | `backend/tests/test_ai.py:36` |
| 16 | `POST /integrations/github/connect` | `/api/v1/workspaces/{workspace_id}/integrations/github/connect` | **PASS** | `backend/app/api/v1/integrations.py:57` | `backend/tests/test_integrations.py:66` |
| 17 | `POST /webhooks/github` | `/api/v1/webhooks/github` | **PASS** | `backend/app/api/v1/webhooks.py:29` | `backend/tests/test_integrations.py:125,152` |
| 18 | `GET /audit-events` | `/api/v1/workspaces/{workspace_id}/audit-events` | **PASS** | `backend/app/api/v1/audit.py:20` | `backend/tests/test_tenancy_rbac.py:72`, `backend/tests/test_incidents.py:26` |

Additional platform endpoints: `GET /healthz`, `GET /readyz`, `GET /metrics`, `GET /api/v1/meta` (`backend/app/api/v1/health.py:27,32,67,87`).

---

## 4. Frontend surface

Source: PRD §6 UX key screens and the 10-view navigation. The frontend is React 18 + TypeScript strict with hand-written CSS.

| View | Status | Evidence | Gap |
| :--- | :---: | :--- | :--- |
| Login | **PASS** | `frontend/src/pages/LoginPage.tsx`; `frontend/src/App.tsx:62` | — |
| Register | **PASS** | `frontend/src/pages/RegisterPage.tsx`; `frontend/src/App.tsx:63` | — |
| Overview | **PASS** | `frontend/src/pages/OverviewPage.tsx`; `frontend/src/App.tsx:74` | — |
| Services list/create | **PASS** | `frontend/src/pages/ServicesPage.tsx`; `frontend/src/App.tsx:75` | — |
| Service detail / health history | **MISSING** | No `/services/:serviceId` route. `ServicesPage` row click targets `/services/${row.id}`; the catch-all redirects to `/`. | **G6** |
| Logs | **MISSING** | `frontend/src/App.tsx:76` renders `PlannedPage` | **G3** |
| Alerts | **MISSING** | `frontend/src/App.tsx:77` renders `PlannedPage` | **G4** |
| Notification centre | **MISSING** | No route; endpoint exists at `backend/app/api/v1/workspaces.py:485` | **G4** |
| Incidents list / detail | **MISSING** | `frontend/src/App.tsx:78-79` render `PlannedPage` | **G1** |
| Deployments | **MISSING** | `frontend/src/App.tsx:80` renders `PlannedPage` | **G2** |
| Integrations | **MISSING** | `frontend/src/App.tsx:82` renders `PlannedPage` | **G2** |
| Reports | **MISSING** | `frontend/src/App.tsx:83` renders `PlannedPage` | **G5** |
| Settings / Audit / members | **MISSING** | `frontend/src/App.tsx:84` renders `PlannedPage` | **G5** |
| Security | **POST-MVP** | `frontend/src/App.tsx:81` renders `PlannedPage`; PRD §6 marks Security as post-MVP / limited pilot | Not counted as an MVP gap |

---

## 5. Gap register

Each gap has a GitHub issue. The UI gaps are PARTIAL in the audit because the backend and tests exist; the missing part is the user-facing screen. The follow-up gaps are the items requested in addition to the audit.

| Gap | Status | Description | Issue |
| :---: | :---: | :--- | :--- |
| **G1** | PARTIAL | Incident queue/detail UI: timeline, evidence, 7 states, owner/status, AI panel and feedback | [#11](https://github.com/parottaaah/Operation-zero/issues/11) |
| **G2** | PARTIAL | Deployments/integrations UI: GitHub scopes, test, revoke, deployment context | [#12](https://github.com/parottaaah/Operation-zero/issues/12) |
| **G3** | PARTIAL | Log explorer UI: filters, cursor pagination, event detail, redaction metadata | [#13](https://github.com/parottaaah/Operation-zero/issues/13) |
| **G4** | PARTIAL | Alerts queue/rules and notification centre UI | [#14](https://github.com/parottaaah/Operation-zero/issues/14) |
| **G5** | PARTIAL | Reports, audit search and settings/member-management UI | [#15](https://github.com/parottaaah/Operation-zero/issues/15) |
| **G6** | PARTIAL | Service detail and health-history UI (route missing entirely) | [#16](https://github.com/parottaaah/Operation-zero/issues/16) |
| **G7** | MISSING | Run pytest against real PostgreSQL in CI (currently SQLite fixtures) | [#17](https://github.com/parottaaah/Operation-zero/issues/17) |
| **G8** | PARTIAL | Real Redis rate-limit integration test. PDF generation is already covered by `backend/tests/test_incidents.py:161` | [#18](https://github.com/parottaaah/Operation-zero/issues/18) |
| **G9** | MISSING | Pin or lock backend Python dependencies for reproducible builds | [#19](https://github.com/parottaaah/Operation-zero/issues/19) |
| **G10** | MISSING | Pin GitHub Actions to commit SHAs | [#20](https://github.com/parottaaah/Operation-zero/issues/20) |
| **G11** | MISSING | `frontend/Dockerfile` uses `npm install`; switch to `npm ci` | [#21](https://github.com/parottaaah/Operation-zero/issues/21) |
| **G12** | MISSING | Container start + health-check smoke test in CI (Docker Compose) | [#22](https://github.com/parottaaah/Operation-zero/issues/22) |
| **G13** | PARTIAL | Remaining MEDIUM/LOW Trivy findings: pip 25.0.1, passwd/login.defs, xz-libs, libxpm | [#23](https://github.com/parottaaah/Operation-zero/issues/23) |
| **G14** | MISSING | Frontend unit/smoke tests after the Vite 8 / React Router 7 upgrade | [#24](https://github.com/parottaaah/Operation-zero/issues/24) |
| **G15** | MISSING | Document in `AGENTS.md` that only the owner and Pi commit to branches | [#25](https://github.com/parottaaah/Operation-zero/issues/25) |
| **G16** | OPEN | Decide on Node 26 (Dependabot PR #3) after the frontend smoke test | [#26](https://github.com/parottaaah/Operation-zero/issues/26) |

---

## 6. What is already verified

- **97 backend tests pass** (`cd backend && python -m pytest`).
- **Ruff lint and format pass** on `app` and `tests`.
- **Frontend production build passes** (`npm ci && npm run build`) with Vite 8 / React Router 7.
- **CI on `main` is green** for the `CI` and `CodeQL` workflows at `f18a928`. The separate `Dependabot Updates` workflow failed while resolving a React 19 peer update; that is not the CI pipeline.
- **Trivy CRITICAL/HIGH gate:** the merged image scans report 0 open CRITICAL/HIGH. Remaining findings are MEDIUM/LOW/UNKNOWN (G13).

## 7. What this audit does not claim

- No SOC 2, ISO 27001 or GDPR compliance is claimed. The PRD explicitly requires policies, evidence, operational processes and independent assessment for those.
- No MVP acceptance criterion is marked PASS merely because a route exists. Where the PRD requires a user-visible surface, the missing screen is recorded as PARTIAL/MISSING.
- Post-MVP items (OpenTelemetry traces/metrics, Slack/Jira, Trivy/Semgrep ingestion, on-call schedules, multi-region, self-hosted retention controls, approval-gated runbooks) are out of scope.
- No PRD open question in section 12 is decided by this audit.

## 8. Reproduce

```bash
cd backend
ruff check app tests
ruff format --check app tests
python -m pytest

cd ../frontend
npm ci
npm run build

gh run list --branch main --limit 3
```

The test suite currently uses in-memory SQLite fixtures (`backend/tests/conftest.py:22-27`), and Redis is disabled in tests (`:60`). That is why G7 and G8 exist.
