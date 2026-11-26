# OPERATION ZERO — Product Requirements Document

**Unified Engineering Operations & Incident Intelligence Platform**  
Draft for discovery and engineering planning · Version 1.0 · 26 November 2026 · Owner: Project team

A practical product blueprint for monitoring, investigation, incident coordination and evidence-grounded AI assistance.

---

## How to review this document

**Why you are reading this.** This PRD defines the product direction and an initial implementation baseline for OPERATION ZERO. It is detailed enough to guide discovery, architecture and sprint planning, though it does not replace user research, a formal threat model, technical design reviews or validation in a real deployment environment. Requirements marked **Must** (MVP) belong in the first usable release; post-MVP items stay out unless user research proves a compelling need.

**Read in this order.**
1. **Words we use** — shared operational and technical vocabulary.
2. **Sections 1–6** — problem, users, hypotheses, mission, roadmap and MVP scope.
3. **Sections 7–9** — localization, data privacy/security, architecture, data model and APIs.
4. **Sections 10–15** — metrics, launch, execution plan & milestones, risks, open questions, decisions, ownership and sign-off.

**How to comment.**
* Start each comment with a tag:
  * **[B] Blocker** — stops shipping or breaks a security/safety rule.
  * **[Q] Question** — unclear or missing requirement.
  * **[S] Suggestion** — a better approach or trade-off.
  * **[N] Nit** — wording, formatting or minor detail.
* Tag the relevant role owner on anything that requires a decision.

| You are… | Please focus on |
| :--- | :--- |
| Product owner | Sections 2, 3, 6 and 10: personas, MVP scope, acceptance criteria and pilot metrics |
| Backend / Platform / DevOps engineer | Section 9 and Section 11: modular monolith architecture, data model, APIs, CI/CD and runbooks |
| Frontend engineer | Section 6 (UX/UI) and Section 7: control-room navigation, key screens and WCAG 2.2 AA |
| AI engineer | Section 6 (AI guardrails) and Section 9: evidence-grounded output, citations and prompt-injection defense |
| Security reviewer | Section 8, Section 9 and Section 12: tenant isolation, SSRF, webhook verification and compliance boundaries |

Review cadence: At each major milestone or scope change.

---

## Words we use

| Term | Meaning |
| :--- | :--- |
| Telemetry | Operational data such as logs, metrics and traces |
| Log event | A timestamped record describing an application or system event |
| Metric | A numeric measurement tracked over time, such as latency or CPU usage |
| Trace | A representation of a request's path through one or more services |
| Alert | A signal that a configured condition has been met |
| Incident | A tracked operational event requiring investigation or response |
| Root-cause hypothesis | A possible explanation that must be validated against evidence |
| Webhook | An HTTP callback sent by an external system when an event occurs |
| RBAC | Role-based access control |
| SSRF | Server-side request forgery, where a server is induced to make unintended requests |
| RAG | Retrieval-augmented generation: supplying relevant retrieved information to an AI model |
| SLO | Service-level objective, a defined target for service reliability |

---

# Part 1 · OPERATION ZERO

Make operational incidents understandable, traceable and actionable by connecting system signals to the engineering context around them. OPERATION ZERO brings application health monitoring, structured log exploration, incident management, deployment context, security signals and human-controlled, evidence-grounded AI investigation into one workspace for small and mid-sized software teams.

## 1. Overview card

| Field | Entry |
| :--- | :--- |
| Product owner | Project team (Product owner role) |
| Team | Product owner, Frontend engineer, Backend engineer, Platform / DevOps engineer, AI engineer, Security reviewer (one person may cover multiple roles in a solo build, tracked separately) |
| Status | Version 1.0 — Draft for discovery and engineering planning |
| Edition | Web-based B2B SaaS / self-hostable engineering operations platform |
| Target dates | Indicative 13–17 weeks from Phase 0 discovery to Phase 7 hardening and pilot (planning estimate, not a commitment) |
| Primary build focus | MVP followed by staged post-MVP expansion (reliable monitoring and incident workflows first, source-control context next, evidence-grounded AI after) |

## 2. Problem and user

**Problem.** When a production system degrades, engineers jump between disconnected monitoring tools, log systems, Git history, deployment dashboards, chat threads and ticketing tools. Signals are fragmented, alerts are noisy or duplicated, handovers lose investigation context and decision rationale, root-cause analysis is inconsistent, security and reliability workflows stay siloed, and post-incident reports take too long and miss evidence links or action owners.

| Segment | Language | Where | Role · context | Primary? |
| :--- | :--- | :--- | :--- | :--- |
| Software Engineer | English | Small and mid-sized software teams | Searches logs, inspects service health, links commits and records investigation findings | Yes |
| SRE / DevOps Engineer | English | Small and mid-sized software teams | Detects degradation, triages alerts, acknowledges incidents, assigns owners and coordinates recovery | Yes |
| Security Engineer | English | Small and mid-sized software teams | Reviews security signals, assesses severity, assigns remediation and verifies closure | Yes |
| Engineering Lead | English | Small and mid-sized software teams | Tracks operational risk, incident overview, ownership, timelines and post-incident follow-ups | Yes |
| Platform Administrator | English | Organization workspaces | Configures workspaces, integrations, RBAC access and data retention | Secondary |
| Read-Only Stakeholder | English | Organization workspaces | Views approved incident summaries and service status without accessing sensitive raw telemetry | Secondary |

**Voice of the user.** To collect during Phase 0 discovery interviews across candidate initial segments (student developer teams, small SaaS companies, agencies or internal IT teams).

## 3. Hypotheses and how we test them

| # | We believe… | Test | Pass / stop signal |
| :--- | :--- | :--- | :--- |
| H1 | Initial customers are small engineering teams that need operational visibility without adopting a complex enterprise suite | Phase 0 discovery interviews and pilot onboarding with small engineering teams | Pass: pilot teams connect services and use the workspace weekly; Stop: teams prefer existing fragmented tools |
| H2 | Users will connect a limited number of services and repositories first | Track activation and connected services/repositories per active pilot workspace | Pass: teams complete onboarding and receive first health checks quickly; Stop: setup friction blocks first service registration |
| H3 | Teams value actionable context and incident workflow over a large number of charts | Measure time to assemble context and workflow completion in controlled pilot incidents | Pass: faster triage and high resolution completion; Stop: users request custom dashboards before using incident timelines |
| H4 | AI-generated summaries are useful only when evidence is visible and claims are appropriately qualified | Pilot ratings of AI suggestions (useful, incorrect, incomplete) and evidence-link click-through | Pass: users trust and accept/edit cited summaries; Stop: users ignore AI output or flag ungrounded claims |
| H5 | Users will accept a collector or integration only when its permissions, data flow and resource usage are transparent | Display explicit permission scopes, test connection flow and data-processing notices during onboarding | Pass: admins complete GitHub and log ingestion setup; Stop: admins abandon setup over permission or privacy concerns |

## 4. Mission and business fit

**Mission fit.** Provide one dependable operational workspace that connects telemetry, deployments, security findings and incident workflows, with AI assistance that is grounded in evidence and controlled by people. Core product principles: **Evidence before explanation**, **Human control by default**, **Useful before intelligent**, **Progressive complexity**, **Secure by design** and **Operational clarity**.

| Item | Amount | Billing | Notes |
| :--- | :--- | :--- | :--- |
| Discovery / Pilot deployment | To set after baseline pilot | Pilot agreement | Validate activation, triage speed and workflow completion before claiming commercial impact |
| B2B SaaS workspace | To set | Subscription (TBD) | Multi-tenant hosted web platform |
| Self-hosted deployment | To set (Post-MVP) | Licence / Enterprise (TBD) | Containerized deployment with organization-level retention controls |

**Delivery & adoption motion.** Discovery & interviews → Synthetic demo walkthroughs → Controlled pilot (cloud-hosted or self-hosted, to decide in discovery) → Staged post-MVP expansion.

**Cost to serve.** Driven primarily by log ingestion volume, storage retention, background worker compute and third-party LLM API calls. Controlled via payload caps, bounded log queries, async ingestion, retention policies and sampling where appropriate.

## 5. Vision and roadmap

**Vision.** A world where engineering teams can understand system behaviour, investigate incidents and coordinate safe resolutions without losing context across disconnected tools—without promising unsafe, fully autonomous remediation.

| Horizon | What | Why | Target |
| :--- | :--- | :--- | :--- |
| Now (Phase 0–1) | Discovery, architecture, threat model, auth, workspaces, RBAC, PostgreSQL/Redis, frontend shell, CI | Establish secure multi-tenant foundation | Weeks 1–3 |
| Now (Phase 2–3) | Service registry, HTTP health checks, structured JSON log ingestion, log explorer, alert rules, deduplication and in-app/email notifications | Deliver reliable monitoring core before intelligence | Weeks 4–8 |
| Now (Phase 4–5) | Incident lifecycle, timeline, ownership, manual evidence linking, PDF/Markdown reports, GitHub OAuth/App integration and verified webhooks | Connect operational symptoms to release/commit context | Weeks 9–12 |
| Now (Phase 6–7) | Evidence-grounded AI summaries & hypotheses, user feedback, security/load/AI-eval testing, runbooks and pilot launch | Complete MVP with provable safety and reliability | Weeks 13–17 |
| Next (Post-MVP) | OpenTelemetry metrics/traces, advanced alert grouping & maintenance windows, Slack/Jira/cloud integrations, custom dashboards, dependency maps, Trivy/Semgrep security ingestion, on-call/escalation, self-hosted retention controls, approval-gated runbooks | Expand observability, ecosystem fit and controlled automation | Post-MVP |
| Later (Deferred) | Automatic production remediation, unrestricted shell execution, broad internet asset discovery, advanced SIEM correlation, multi-region enterprise deployment, integration marketplace | Deferred until safety, demand and operational maturity are proven | Future |

## 6. Scope and user stories

| In scope (MVP) | Out of scope (for now) |
| :--- | :--- |
| User auth, multi-workspace support and server-side RBAC (Owner, Admin, Engineer, Security Analyst, Viewer) | Replacing mature observability suites, SIEMs, ticketing systems or source-control platforms |
| Service registry and HTTP health checks with configurable intervals, timeouts, thresholds and SSRF protections | Autonomous production changes, automated code deploys or unrestricted shell execution |
| Authenticated structured JSON log ingestion API, bounded search/filtering and pre-persistence secret redaction | Guaranteeing a definitive root cause from incomplete telemetry |
| Basic alert rules (availability, error rate, latency), deduplication window, ack/mute, in-app & email alerts | Offensive security testing or unauthorized asset scanning |
| Full incident lifecycle (Open → Closed), ownership, timeline, manual evidence linking and PDF/Markdown export | General-purpose workflow automation platform in Release 1 |
| Least-privilege GitHub integration (OAuth/App) with signature-verified webhooks for commits/PRs/deployments | Supporting every cloud provider, language and telemetry standard at launch |
| Evidence-grounded AI incident summaries, hypotheses, qualitative confidence and user feedback (read-only) | OpenTelemetry traces/metrics, Slack/Jira, Trivy/Semgrep ingestion, on-call schedules (Post-MVP) |
| Audit log for auth-sensitive actions, role changes, integration changes, incident transitions and approvals | Multi-region enterprise deployment and integration marketplace (Deferred) |

| # | As a… | I want to… | So that… | Priority |
| :--- | :--- | :--- | :--- | :--- |
| OZ1 | Workspace Admin | create a workspace, invite teammates and enforce explicit server-side roles (Owner, Admin, Engineer, Security Analyst, Viewer) | teams collaborate safely with zero cross-workspace data leakage | Must |
| OZ2 | SRE / Software Engineer | register services, configure HTTP health checks and inspect service health history by environment and time range | I detect degradation early without risking internal network SSRF | Must |
| OZ3 | Software Engineer | ingest structured JSON logs and filter them by time, severity, service, environment and text with sensitive fields redacted | I locate error evidence quickly without exposing secrets or unbounded queries | Must |
| OZ4 | SRE / DevOps Engineer | configure alert rules for availability, error counts/rates and latency, then acknowledge, mute or convert deduplicated alerts into incidents | noisy signals are controlled and real issues move cleanly into triage | Must |
| OZ5 | SRE / Software Engineer | manage an incident through Open, Acknowledged, Investigating, Mitigating, Monitoring, Resolved and Closed with timeline entries, linked evidence and resolution notes | handovers preserve investigation history, decisions and follow-up actions | Must |
| OZ6 | Software Engineer | connect a GitHub repository via least-privilege OAuth/App and inspect signature-verified push, PR and deployment events alongside a service | I see temporal release context without falsely assuming a commit is the root cause | Must |
| OZ7 | Engineer / Lead | request an AI incident summary separating observed facts (with source links), inferred hypotheses, missing info and next checks, and rate its usefulness | I speed up triage while verifying every claim and keeping humans in full control | Must |
| OZ8 | Admin / Lead | inspect searchable audit logs and export permission-aware incident reports in PDF or Markdown | accountability, post-incident learning and review trails are preserved | Must |

### UX / UI control-room standards
Professional engineering control-room aesthetic prioritizing readability over decorative dashboards.
* **Main navigation (10 views):** Overview, Services, Logs, Alerts, Incidents, Deployments, Security (post-MVP / limited pilot), Integrations, Reports, Settings.
* **Key screens:** Overview (active incidents, service health, recent alerts/deployments, ingestion health), Service detail, Log explorer (time range, filters, query, table, event panel), Incident list, Incident detail (summary, status controls, owner, timeline, evidence links, AI assistant, resolution), Integration setup (scopes, test, status, revoke), Settings / Audit.
* **UX quality rules:** Every table handles loading, empty, error and partial-result states; destructive actions require confirmation explaining impact; statuses never rely on colour alone (use labels + icons); keyboard-accessible controls with visible focus states; contextual explanations for severity, alert state and AI uncertainty.

### AI investigation guardrails
* **4-part output format:** (a) Observed facts with clickable source references, (b) Inferred hypotheses with reasoning and qualitative confidence (never unvalidated calibrated probabilities), (c) Missing information, (d) Recommended next checks.
* **Security controls:** Treat logs, repo content, issue text and webhooks as untrusted data (prompt-injection defense); never allow retrieved data to override policy or escalate tool access; narrow read-only tool allowlist in MVP; redact secrets before sending context to external LLMs; log provider, model ID, prompt version, evidence IDs and feedback; never execute shell commands or modify infrastructure automatically.

### Definition of done
* Passes unit, integration, OpenAPI contract, end-to-end, security (tenant isolation, privilege escalation, injection, rate limiting, secret exposure), load and AI-evaluation (citation, hallucination, prompt-injection, permission-boundary) tests.
* All 10 MVP acceptance criteria pass: workspace/RBAC creation; service registration & pass/fail health checks; authenticated structured log ingestion rejecting invalid/unauthorized payloads; alert rule firing on threshold breach; alert-to-incident conversion with ownership and status updates; full incident timeline & linked evidence; verified GitHub webhooks visible as context; evidence-cited AI summary clearly separating hypotheses; strict cross-workspace isolation; audit logging of sensitive actions.

### Demo (end-to-end walkthrough)
Create workspace and register a service with an HTTP health check → connect GitHub repo after reviewing explicit scopes and test event → trigger a simulated threshold breach to fire a deduplicated alert → convert alert to incident and assign owner → inspect failing health history, filtered structured logs and recent deployment context → link evidence and generate an evidence-cited AI summary (inspecting source links and qualitative confidence) → record findings, resolve incident with follow-up actions → export PDF/Markdown incident report and verify entries in the audit log.

## 7. Language and localization

| Field | Entry |
| :--- | :--- |
| Lead language | English |
| Second language | None in MVP (to evaluate post-pilot) |
| Accessibility standard | WCAG 2.2 AA practices for core workflows (keyboard navigation, visible focus, non-colour status indicators) |
| Timestamps and timezones | Timezone-aware timestamps throughout; workspace timezone clearly displayed in UI |
| Export formats | PDF and Markdown (redacted according to viewer permissions) |

## 8. Data, privacy and compliance

| Data item | Personal? | Stored where | Consent · basis | Retention |
| :--- | :--- | :--- | :--- | :--- |
| User profile & auth records | Yes | Managed IdP & PostgreSQL (tenant-scoped) | Account registration / workspace membership | Account / workspace lifecycle; secure deletion supported |
| Structured application logs & health checks | Possibly (minimized & redacted pre-persistence) | PostgreSQL (indexed; partitioned/archived at scale) | Workspace configuration & ingestion auth | Configurable telemetry retention policy |
| Incident records, timelines & evidence links | Yes (actor IDs, notes) | PostgreSQL | Workspace operational agreement | Configurable workspace retention policy |
| GitHub OAuth tokens & integration secrets | No (credentials) | Dedicated secrets manager / encrypted store (never plaintext in DB/logs) | Explicit admin authorization & scope review | Until rotated, revoked or deleted |
| AI analysis prompts, context & outputs | Minimized (secrets redacted before external LLM calls) | PostgreSQL & third-party AI provider (if configured) | Clear third-party AI data-processing notice | Separate AI analysis retention policy |
| Audit events | Yes (actor IDs, actions, safe metadata) | PostgreSQL (transactional with incident transitions) | Security & operational governance | Separate audit retention policy |
| Reports & attachments | Possibly (permission-redacted) | Private S3-compatible object storage | Workspace authorization | Configurable retention / secure deletion |

**Security and compliance posture.** Enforce TLS in transit, encryption at rest, managed identity or secure password hashing (no custom cryptography), server-side RBAC and tenant isolation on every API and worker, webhook signature/timestamp/replay checks, SSRF private-range blocking by default on health checks, CSRF/CORS/cookie hardening, rate limiting on auth/ingestion/AI endpoints, and CI scanning (dependencies, SAST, containers, secrets). Minimize personal data and avoid collecting source code or full payloads unless explicitly authorized. **Compliance boundary:** Do not claim SOC 2, ISO 27001 or GDPR compliance solely from engineering controls; formal compliance requires scoped policies, evidence, operational processes and independent assessment.

## 9. Architecture and dependencies

**Recommended pattern.** Modular monolith for MVP with clear domain boundaries (Identity & Workspace, Service Registry, Health Check Scheduler/Executor, Log Ingestion & Query, Alert Evaluation Engine, Incident Management, Integration & Webhook Gateway, AI Investigation Orchestrator, Audit & Reporting, Notification Worker), enabling later extraction of high-volume ingestion and workers.

| Component | Choice | Hosted where |
| :--- | :--- | :--- |
| Web frontend | React + TypeScript + Vite or Next.js | Managed container hosting / Docker Compose (local) |
| API backend | Python FastAPI (`/api/v1`, OpenAPI documented) | Managed container hosting / Docker Compose (local) |
| Primary database | PostgreSQL (UUIDs, strict `workspace_id` tenant scoping) | Managed PostgreSQL / Docker Compose (local) |
| Cache / queue | Redis (rate limiting, job coordination, short-lived cache) | Managed Redis / Docker Compose (local) |
| Background workers | Python workers (Celery / RQ / equivalent) | Independent worker containers |
| Telemetry conventions | OpenTelemetry-compatible model | API gateway & ingestion pipeline |
| AI service | Provider-agnostic LLM adapter (async orchestration) | External LLM provider or configured endpoint |
| Object storage | S3-compatible storage (private access enforced) | Cloud / self-hosted S3-compatible store |
| Deployment | Docker Compose (local); managed container hosting (staging/prod) | Cloud-hosted or self-hosted (TBD in discovery) |

**Data flow & architecture constraints.** Authenticated telemetry/webhooks hit the API gateway → validated for source, workspace, schema and size → stored and processed asynchronously by workers (health checks, alert evaluation, deduplication, notifications, AI orchestration, reports). Keep API handlers short; use idempotency keys for ingestion/webhooks; wrap incident transitions and audit logging in database transactions; enforce tenant filtering at the data-access layer; design cursor pagination, indexes and retention upfront.

**Initial Data Model (16 core entities).** `User`, `Workspace`, `Membership`, `Service`, `HealthCheck`, `HealthCheckResult`, `LogEvent`, `AlertRule`, `Alert`, `Incident`, `IncidentEvent`, `EvidenceLink`, `Integration`, `WebhookEvent`, `AuditEvent`, `AIAnalysis`.

**Core API surface (`/api/v1`, JSON, cursor pagination, rate-limited, idempotent).**
* **Workspaces & Services:** `POST /workspaces`, `GET /workspaces/{id}`, `POST /services`, `GET /services`, `GET /services/{id}/health`
* **Logs & Alerts:** `POST /ingest/logs`, `GET /logs`, `POST /alert-rules`, `GET /alerts`, `POST /alerts/{id}/acknowledge`
* **Incidents & AI:** `POST /incidents`, `GET /incidents/{id}`, `PATCH /incidents/{id}`, `POST /incidents/{id}/evidence`, `POST /incidents/{id}/ai-analysis`
* **Integrations & Audit:** `POST /integrations/github/connect`, `POST /webhooks/github`, `GET /audit-events`

**Non-functional baselines.** Monitor an explicit MVP availability objective (no unsupported uptime promises); establish p95 latency targets under pilot load; scale ingestion/workers independently from interactive traffic; retry transient worker failures with bounded exponential backoff and dead-letter queues; instrument the platform itself with structured logs, metrics, traces and health endpoints; document backup, restore and disaster-recovery procedures before pilot.

| Depends on | Owner | Needed by | Status |
| :--- | :--- | :--- | :--- |
| Discovery interviews, architecture & threat model | Product owner / Security reviewer | Phase 0 (Week 1) | Planned |
| Auth, workspace RBAC, DB schema, frontend shell & CI | Backend / Frontend / DevOps | Phase 1 (Weeks 2–3) | Planned |
| Service registry & SSRF-safe health check scheduler | Backend / Security | Phase 2 (Weeks 4–5) | Planned |
| Structured log ingestion, redaction, search & alert engine | Backend | Phase 3 (Weeks 6–8) | Planned |
| Incident lifecycle, transactional audit log & report export | Backend / Frontend | Phase 4 (Weeks 9–10) | Planned |
| GitHub OAuth/App scopes & verified webhook gateway | Backend / Security | Phase 5 (Weeks 11–12) | Planned |
| Evidence-grounded AI adapter, prompt-injection evals & feedback UI | AI engineer / Frontend | Phase 6 (Weeks 13–14) | Planned |
| Load tests, security tests, runbooks & staging smoke tests | QA / Security / DevOps | Phase 7 (Weeks 15–17) | Planned |

## 10. Success metrics

| Metric | Baseline | Target | By when |
| :--- | :--- | :--- | :--- |
| Activation (workspaces registering a service & getting first health result) | 0 | Establish baseline during pilot | Pilot launch |
| Time to acknowledge (median creation → acknowledgement) | Establish in pilot | Reduce vs. pilot baseline | Post-pilot review |
| Time to assemble context (locate relevant logs & deploys for test incident) | Establish in pilot | Measure & improve vs. baseline | Pilot evaluation |
| Evidence coverage (hypotheses with ≥1 linked supporting signal) | — | Track & maximize in pilot | MVP pilot |
| Alert usefulness (user-rated actionable vs. non-actionable alerts) | — | Weekly review during pilot | Pilot weekly |
| Incident workflow completion (resolved with owner, timeline, resolution note) | 0 | High completion across pilot workspaces | Pilot review |
| AI usefulness (user ratings: accepted, edited, rejected) | — | Track continuously in pilot | Phase 6–7 |
| Ingestion & platform reliability (API latency, rejection/duplicate rate, webhook failures, worker lag) | — | Tracked via internal observability | Phase 7 pilot |
| Adoption (weekly active users & connected services/repos per workspace) | 0 | Set after baseline pilot | Post-pilot |
| Security posture (unresolved high-severity findings in own deps/infra) | — | Zero unresolved high-severity before pilot | Continuous CI |

*Targets are finalized after a baseline pilot; avoid claiming business impact until measured with real users. Do not use sensitive telemetry content as product analytics.*

## 11. Launch and go-to-market

| Field | Entry |
| :--- | :--- |
| Launch type | Local (Docker Compose) → Development → Staging (release candidate + smoke tests) → Controlled Production / Pilot (authorized approval + rollback) |
| First customers | Small engineering teams (exact initial segment—student dev teams, small SaaS, agencies or internal IT—to confirm in Phase 0 discovery) |
| Channels | Direct pilot outreach, public portfolio/GitHub showcase and synthetic demo environment |
| Launch materials & portfolio deliverables | Public README (problem, screenshots, demo, setup), architecture diagram & ADRs, DB ER diagram & OpenAPI docs, threat model & security overview, test/CI summary, synthetic demo environment, 2–3 incident walkthroughs, short demo video, simulated failure postmortem, public roadmap |
| Support & operations | Operational runbooks covering DB restore, queue backlog, failed ingestion, expired integration credentials, webhook failures, AI provider outage and security incident response |

**CI/CD release gate.** PR + code review → formatting, linting, type checks, unit tests → dependency & secret scanning → versioned container build → CI integration tests → staging deploy & smoke tests → authorized approval for production release with migration/rollback verification.

## 11a. Execution plan and 6 milestones

**Execution plan.** Execute OPERATION ZERO in sequential, gated phases starting with discovery, threat modeling and architecture validation before standing up the modular monolith foundation. Deliver core service monitoring, structured log ingestion and alert handling first so operational telemetry and incident workflows are dependable before adding source-control context and read-only, evidence-grounded AI assistance. Gate every milestone transition on passing tests, tenant-isolation verification, secret/SSRF safeguards and stakeholder review.

| Milestone | Focus | Key deliverables | Exit criteria |
| :--- | :--- | :--- | :--- |
| **M1: Discovery & Architecture** | Problem validation, architecture & threat model | Discovery notes across candidate segments, modular monolith blueprint, data model & API contract baseline, threat model & SSRF/tenant-isolation controls | Core architecture, security boundaries and initial MVP backlog approved |
| **M2: Foundation & Access** | Auth, workspaces, RBAC & delivery pipeline | User auth, workspace creation, server-side RBAC (Owner, Admin, Engineer, Security Analyst, Viewer), PostgreSQL/Redis setup, frontend shell, CI/CD pipeline | Multi-workspace access enforced with zero cross-tenant leakage and green CI checks |
| **M3: Monitoring & Log Explorer** | Service registry, health checks & structured logs | Service registry, HTTP health check scheduler with SSRF protection, authenticated JSON log ingestion, pre-persistence redaction, bounded log explorer | Services report pass/fail health states and searchable structured logs redact sensitive fields |
| **M4: Alerts & Incident Core** | Alert rules, deduplication & incident lifecycle | Availability/error-rate/latency alert rules, deduplication window, ack/mute, in-app & email notifications, full incident states (Open → Closed), timeline, evidence links & reports | Alerts convert into tracked incidents with audit-consistent timelines and exported reports |
| **M5: GitHub & AI Investigation** | Deployment context & evidence-grounded AI | Least-privilege GitHub OAuth/App connection, signature/replay-verified webhooks, commit/PR/deployment context, 4-part AI summaries & hypotheses with source links and feedback | Verified GitHub events display as temporal context and AI outputs cite evidence without auto-remediation |
| **M6: Hardening & Pilot Launch** | Quality gates, runbooks & controlled pilot | Unit, integration, contract, E2E, security, load and AI-eval suites; operational runbooks; staging smoke tests; pilot onboarding & baseline metrics collection | All MVP acceptance criteria pass, high-severity CI issues resolved and pilot workspace active |

## 12. Risks and open questions

| Risk | Likelihood | Impact | Mitigation | Owner |
| :--- | :--- | :--- | :--- | :--- |
| Scope creep delays usable MVP | High | High | Prioritize core incident workflow; strictly defer advanced automation and broad integrations | Product owner |
| Noisy alerts cause users to ignore platform | Medium | High | Tune thresholds, deduplicate within grouping windows and review alert usefulness weekly | Backend / Product |
| AI hallucination damages user trust | Medium | High | Require source evidence links, qualitative uncertainty labels, human review and AI evaluation tests | AI engineer |
| Sensitive data exposure | Medium | High | Minimize collection, redact pre-persistence/pre-LLM, encrypt secrets and enforce tenant isolation | Security / Backend |
| Integration complexity creates flaky connectors | Medium | Medium | Launch with one well-tested integration (GitHub) and transparent minimal scopes | Backend engineer |
| High telemetry volume degrades cost/performance | Medium | High | Enforce payload limits, retention policies, targeted indexing, sampling and async ingestion | Backend / DevOps |
| Unsafe health checks cause SSRF / internal exposure | Medium | High | Block private network ranges by default, validate DNS/redirects and isolate the checker | Security / Backend |
| External AI provider outage disrupts workflows | Medium | Medium | Graceful degradation: core monitoring, logs, alerts and incident workflows run without AI | AI / Backend |

**Open questions for discovery:**
1. Which initial customer segment is most accessible for interviews: student developer teams, small SaaS companies, agencies or internal IT teams?
2. Which telemetry source should be supported first: application logs, health checks or OpenTelemetry?
3. Should the first pilot be cloud-hosted, self-hosted or both?
4. What log fields are essential for the first use case, and which fields must be redacted by default?
5. Which GitHub permissions are strictly necessary for the chosen workflow?
6. Which AI provider and data-processing arrangement is acceptable to pilot users?
7. What retention period and expected event volume should the MVP support?
8. Which notification channel is most useful for initial target users (in-app, email, or other)?

## 13. Decision log

| Date | Decision | Decider |
| :--- | :--- | :--- |
| 26 Nov 2026 | Adopt a modular monolith (FastAPI + PostgreSQL + Redis + Python workers) for MVP rather than microservices | Project team |
| 26 Nov 2026 | Core monitoring and incident workflows must operate independently when AI services are unavailable | Project team |
| 26 Nov 2026 | AI is strictly read-only and evidence-grounded in MVP; no autonomous remediation or shell execution | Project team |
| 26 Nov 2026 | Launch with GitHub (least-privilege OAuth/App + signed webhooks) as the first source-control integration; show commits as temporal context, not proof | Project team |
| 26 Nov 2026 | Block private network ranges by default on HTTP health checks to prevent SSRF unless explicitly enabled and constrained by admin | Project team |

## 14. Who does what

| Area | Does the work | Answers for it | Consulted | Informed |
| :--- | :--- | :--- | :--- | :--- |
| Product decisions & pilot | Product owner | Product owner | Engineering, Pilot stakeholders | Project team |
| Frontend & UX/UI | Frontend engineer | Product owner | Backend engineer, AI engineer | Project team |
| Backend APIs, DB & workers | Backend engineer | Backend engineer | Security reviewer, DevOps | Product owner |
| Platform, CI/CD & runbooks | Platform / DevOps engineer | Platform / DevOps engineer | Backend engineer, Security reviewer | Project team |
| AI orchestration & evals | AI engineer | Product owner | Backend engineer, Security reviewer | Project team |
| Threat model & security testing | Security reviewer | Security reviewer | Backend, DevOps, AI engineer | Product owner |

## 15. Sign-off

| Gate | Name | Decision | Date |
| :--- | :--- | :--- | :--- |
| Product owner | | | |
| Engineering lead (Frontend / Backend / DevOps) | | | |
| AI engineer | | | |
| Security reviewer | | | |

---

### Reviewer questions — OPERATION ZERO

1. Which single pilot customer segment (student teams, small SaaS, agencies or internal IT) should we lock in first so Phase 0 interviews start immediately?
2. If the 13–17 week timeline were cut in half, would you ship monitoring + incidents without GitHub webhooks or without AI summaries first?
3. Should the first pilot run cloud-hosted on managed containers or self-hosted via Docker Compose?
4. What exact redaction rules (tokens, emails, IPs, custom keys) must ship on day one before any external log ingestion?
5. Which external LLM provider (or self-hosted model) satisfies pilot users' data-processing expectations?