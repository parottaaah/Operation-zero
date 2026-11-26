import { Link } from "react-router-dom";
import { Card, Notice, PageHeader } from "../components/ui";

/**
 * Screens whose backend endpoints already exist but whose UI is not built yet.
 *
 * These pages are deliberately explicit rather than empty: the control room should
 * never imply it is showing data it is not showing. Delete an entry from `SCREENS`
 * and add a real page the moment that view lands.
 */
type ScreenKey =
  | "logs"
  | "alerts"
  | "incidents"
  | "incident"
  | "deployments"
  | "security"
  | "integrations"
  | "reports"
  | "settings";

interface ScreenSpec {
  title: string;
  subtitle: string;
  api: string[];
  planned: string[];
}

const SCREENS: Record<ScreenKey, ScreenSpec> = {
  logs: {
    title: "Logs",
    subtitle: "Bounded, redacted log exploration for one workspace.",
    api: [
      "GET /workspaces/{id}/logs with severity, service, text and time-range filters",
      "POST /ingest/logs with an X-Ingestion-Key header and idempotency keys",
      "Redaction of secrets and personal data before persistence",
    ],
    planned: [
      "Filter bar with URL-persisted state and cursor pagination",
      "Event detail panel showing trace id, attributes and redaction count",
      "Copy-ready query links to paste into an incident timeline",
    ],
  },
  alerts: {
    title: "Alerts",
    subtitle: "Fired alerts, deduplication state and the rules behind them.",
    api: [
      "GET /workspaces/{id}/alerts and /alert-rules",
      "PATCH /alerts/{id} for acknowledge, mute and resolve",
      "POST /alerts/{id}/incident to convert a firing alert into an incident",
    ],
    planned: [
      "Alert queue grouped by rule, with occurrence counts",
      "Rule editor for metric, comparator, threshold and window",
      "One-click convert to incident with the alert pre-linked as evidence",
    ],
  },
  incidents: {
    title: "Incidents",
    subtitle: "Every incident with owner, severity and current lifecycle state.",
    api: [
      "GET /workspaces/{id}/incidents (cursor paginated, filterable by status and severity)",
      "POST /workspaces/{id}/incidents to open one manually",
      "Server-enforced lifecycle transitions (open → acknowledged → investigating → …)",
    ],
    planned: [
      "Triage queue with status and severity filters",
      "Inline owner assignment and acknowledgement",
      "Keyboard-first navigation for on-call use",
    ],
  },
  incident: {
    title: "Incident room",
    subtitle: "Timeline, evidence, follow-ups and evidence-grounded AI investigation.",
    api: [
      "GET /incidents/{id} with events, evidence links and AI analysis briefs",
      "POST /incidents/{id}/comments, /evidence, /reports",
      "POST /incidents/{id}/ai-analysis (read-only output, human-reviewed)",
      "PATCH /incidents/{id} with transition and resolution rules enforced server-side",
    ],
    planned: [
      "Timeline with actor, from/to status and inline comments",
      "Evidence list that deep-links to the cited log event or health result",
      "AI panel showing observed facts with citations, hypotheses marked unvalidated",
      "Report export in Markdown and PDF",
    ],
  },
  deployments: {
    title: "Deployments",
    subtitle: "Verified repository and deployment events, shown as context - never as proof of cause.",
    api: [
      "POST /webhooks/github with HMAC signature verification",
      "GET /workspaces/{id}/deployments",
      "Overview already surfaces the most recent verified deliveries",
    ],
    planned: [
      "Delivery list with repository, ref, commit and actor",
      "Timeline overlay against incidents in the same window",
      "Link a deployment into an incident as evidence",
    ],
  },
  security: {
    title: "Security",
    subtitle: "Security-relevant signals alongside reliability signals.",
    api: [
      "Audit trail at GET /workspaces/{id}/audit-events",
      "Redaction reporting on every stored log event",
      "Role-based access control per workspace",
    ],
    planned: [
      "Audit explorer with actor, action and outcome filters",
      "Redaction volume trend per service",
      "Suspicious-ingestion and auth-failure views",
    ],
  },
  integrations: {
    title: "Integrations",
    subtitle: "Least-privilege source-control connections.",
    api: [
      "GitHub OAuth handshake with configurable scopes (default read:user repo:status)",
      "Integration secrets encrypted at rest with a dedicated key",
      "Webhook deliveries recorded with signature-verification outcome",
    ],
    planned: [
      "Connect and revoke flows with the granted scope shown",
      "Delivery log with rejection reasons",
      "Repository selection scoped to a single workspace",
    ],
  },
  reports: {
    title: "Reports",
    subtitle: "Post-incident reports generated from stored evidence.",
    api: [
      "POST /incidents/{id}/reports (Markdown and PDF)",
      "GET /incidents/{id}/reports for the generated artefacts",
      "Redaction level recorded per report",
    ],
    planned: [
      "Report list per incident with generated-at and size",
      "Download and share links",
      "Follow-up action tracking carried into the next incident",
    ],
  },
  settings: {
    title: "Settings",
    subtitle: "Workspace membership, roles and data-retention policy.",
    api: [
      "GET/PATCH /workspaces/{id} for name, timezone and retention windows",
      "GET/POST/PATCH members with role ranking enforced server-side",
      "Audit retention, telemetry retention and AI retention configured separately",
    ],
    planned: [
      "Member management UI with invitation state",
      "Retention controls with an explicit data-processing acknowledgement",
      "Ingestion key rotation with a single-view plaintext reveal",
    ],
  },
};

export default function PlannedPage({ screen }: { screen: ScreenKey }) {
  const spec = SCREENS[screen];

  return (
    <div className="page">
      <PageHeader title={spec.title} subtitle={spec.subtitle} />
      <Notice tone="info">
        This screen is not built yet. The endpoints behind it are implemented and tested; only the
        interface is missing. Nothing on this page is mocked data.
      </Notice>
      <div className="grid cols-2">
        <Card title="Already available over the API">
          <ul className="plain-list">
            {spec.api.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Card>
        <Card title="Planned for this screen">
          <ul className="plain-list">
            {spec.planned.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Card>
      </div>
      <Card title="Working views today">
        <p style={{ margin: 0 }}>
          <Link to="/">Overview</Link> and <Link to="/services">Services</Link> are implemented
          end to end, including the service registration form and ingestion-key reveal.
        </p>
      </Card>
    </div>
  );
}

export type { ScreenKey };
