# Security policy

OPERATION ZERO is an engineering-operations platform that stores service telemetry,
incident data and integration credentials. Security reports are taken seriously.

## Supported versions

Security fixes land on `main` and are tagged from there. The current baseline is
`v0.1.0-baseline`. Older tags and forks are not supported.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting:

<https://github.com/parottaaah/Operation-zero/security/advisories/new>

If that form is unavailable, contact the maintainer through their GitHub profile and
ask for a private channel. Do not include exploit details in a public issue, pull
request or discussion.

Please include:

- affected version or commit,
- a minimal reproduction,
- the impact you believe it has,
- whether the issue crosses a workspace or role boundary.

We aim to acknowledge reports within three business days on a best-effort basis. This
is a small project; there is no bug bounty and no formal response SLA.

## Scope

In scope:

- authentication, session and token handling,
- workspace isolation and role-based access control,
- log ingestion, redaction and retention,
- SSRF protections around HTTP health checks,
- webhook signature and replay handling,
- encryption of integration secrets at rest,
- AI prompt handling, citation integrity and data sent to external providers,
- secrets exposed in the repository, CI logs or build artifacts.

Out of scope:

- findings that require a compromised maintainer account or GitHub itself,
- denial of service through unrealistic volumes without a concrete reproduction,
- vulnerabilities in third-party services we only link to.

## Handling expectations

- Secrets, credentials and personal data must be redacted before persistence and
  before any external LLM call.
- Private network ranges stay blocked by default for health checks.
- AI remains read-only and evidence-grounded; no autonomous remediation.
- Changes must not weaken the invariants in `AGENTS.md`.

This project does not claim SOC 2, ISO 27001 or GDPR certification or compliance.
