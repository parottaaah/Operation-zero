# OPERATION ZERO

Unified engineering operations and incident intelligence: service health, structured logs,
alerts, incidents, deployment context and evidence-grounded AI investigation in one workspace.

The product direction lives in
[`operation_zero_product_requirements_document.md`](./operation_zero_product_requirements_document.md).
This README covers only how to run and verify what is in the repository today.

## Where the build actually is

| Area | State |
| :--- | :--- |
| Backend API (FastAPI + SQLAlchemy 2, Alembic) | Implemented, 97 tests passing |
| Auth, workspaces, RBAC, audit trail | Implemented |
| Service registry, health checks, health history | Implemented |
| Log ingestion + redaction + bounded search | Implemented |
| Alert rules, deduplication, notifications (in-app) | Implemented |
| Incident lifecycle, timeline, evidence links, reports (MD/PDF) | Implemented |
| AI investigation with citation integrity checks | Implemented (`local-deterministic` by default) |
| Background workers (health checks, alert evaluation) | Implemented |
| Frontend: sign-in, register, overview, services, log explorer | Implemented |
| Frontend: alerts, incidents, deployments, security, integrations, reports, settings | **Not built yet** — routes render an explicit "not built" screen that lists the endpoints already available |
| GitHub OAuth / webhooks | Backend implemented, UI not built |

Nothing in the UI is mocked: screens that do not exist say so rather than showing placeholder
numbers.

## Stack

- **Backend** — Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, Postgres (SQLite for local dev/tests),
  Redis (optional in-process fallback), PyJWT, `hashlib.scrypt`, `cryptography.Fernet`, ReportLab.
- **Frontend** — React 18, React Router 6, Vite 5, TypeScript (strict), hand-written CSS.
- **Ops** — Docker Compose (Postgres, Redis, api, worker, nginx-served frontend), Makefile targets.

## Quick start (Docker)

```bash
cp .env.example .env          # then replace OZ_JWT_SECRET and OZ_ENCRYPTION_KEY
make up                       # docker compose up --build
```

- UI: <http://localhost:5173>
- API: <http://localhost:8000> (`/healthz`, `/api/v1/...`, OpenAPI at `/docs`)

Migrations run automatically in the `api` container before uvicorn starts.

## Quick start (local)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env
python -m alembic upgrade head
python -m app.scripts.seed_demo
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api to :8000
```

Optional background workers (health checks and alert evaluation):

```bash
cd backend && python -m app.workers.runner
```

## Demo data

`python -m app.scripts.seed_demo` creates one workspace (`demo-engineering`) with four services,
two hours of health-check history, thirteen redacted log events, three alert rules, two fired
alerts, three incidents (investigating, monitoring, resolved), eight evidence links, one
completed AI analysis and two verified deployment deliveries.

All accounts use the password `DemoZero-2026!`:

| Account | Role |
| :--- | :--- |
| `owner@demo.operation-zero.dev` | owner |
| `engineer@demo.operation-zero.dev` | engineer |
| `analyst@demo.operation-zero.dev` | security_analyst |
| `viewer@demo.operation-zero.dev` | viewer |

The script is idempotent and refuses to run when `OZ_ENV` is production or staging.

```bash
python -m app.scripts.seed_demo --force   # wipe the demo workspace and reseed
```

Service ingestion keys are printed once on creation (only the SHA-256 hash is stored). Health
checks are seeded **disabled** so the demo snapshot stays deterministic; enable one in the UI once
it points at a reachable endpoint.

## Verify

```bash
cd backend && python -m pytest -q          # 97 tests
cd backend && ruff check app tests && ruff format --check app tests
cd frontend && npm run build               # tsc --noEmit + vite build
```

## Repository layout

```
backend/
  app/
    api/v1/       routers: auth, workspaces, services, logs, alerts, incidents, integrations, webhooks, audit
    core/         config, db, security, permissions, errors, rate limiting, observability, pagination
    models/       SQLAlchemy models (identity, service, telemetry, alerting, incident, integration, ai, audit)
    schemas/      Pydantic request/response contracts
    services/     domain logic: incidents, alerts, healthcheck, redaction, ssrf, reports, ai/, audit
    scripts/      seed_demo
    workers/      background runner
  alembic/        migrations
  tests/          API, tenancy/RBAC, worker, AI, seed tests
frontend/
  src/
    pages/        Login, Register, Overview, Services, Logs (+ Planned screen)
    components/   Layout, UI primitives
    auth/         AuthContext (token + workspace selection)
    hooks/        useAsync, useCursorPage (keyset pagination over CursorPage endpoints)
    lib/          api client, types, formatters
```

## Security and privacy notes

- Tenant scoping is enforced in the query layer; RBAC is checked per route via `Permission`.
- Secrets, credentials and personal data are redacted **before** persistence; every log event stores
  its redaction count and the field paths that were masked.
- Health checks go through an SSRF guard (scheme/host/IP validation, redirect limits, optional
  private-network allowlist).
- AI output is advisory and read-only. Facts must carry citations from the stored evidence pack;
  uncited facts are dropped and counted, and hypotheses are labelled unvalidated.
- Integration secrets are encrypted at rest with a dedicated key; `.env` is gitignored and
  `.env.example` ships explicit `CHANGE_ME` guidance.

## Known gaps

1. The seven screens listed as "not built" above.
2. No notification centre UI (endpoint `GET /workspaces/{id}/notifications` exists).
3. No CI pipeline in the repository yet — tests are run locally via `make test`.
