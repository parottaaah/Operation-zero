export type Role = "owner" | "admin" | "engineer" | "security_analyst" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface MembershipSummary {
  workspace_id: string;
  workspace_name: string;
  workspace_slug: string;
  role: Role;
}

export interface Me {
  user: User;
  memberships: MembershipSummary[];
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  telemetry_retention_days: number;
  audit_retention_days: number;
  ai_retention_days: number;
  ai_data_processing_acknowledged: boolean;
  role: Role | null;
  created_at: string;
  updated_at: string;
}

export type Environment = "production" | "staging" | "development";
export type ServiceStatus = "unknown" | "healthy" | "degraded" | "down" | "paused";

export interface HealthCheck {
  id: string;
  service_id: string;
  url: string;
  method: string;
  expected_status_codes: number[];
  interval_seconds: number;
  timeout_seconds: number;
  failure_threshold: number;
  recovery_threshold: number;
  enabled: boolean;
  consecutive_failures: number;
  consecutive_successes: number;
  last_error: string;
  created_at: string;
  updated_at: string;
}

export interface Service {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  environment: Environment;
  description: string;
  owner_team: string;
  status: ServiceStatus;
  last_checked_at: string | null;
  ingestion_key_last4: string;
  health_check: HealthCheck | null;
  created_at: string;
  updated_at: string;
}

export interface ServiceCreated extends Service {
  ingestion_key: string;
}

export interface HealthResult {
  id: string;
  service_id: string;
  status: "pass" | "fail" | "error" | "timeout";
  effective_status: ServiceStatus;
  status_code: number | null;
  latency_ms: number | null;
  error_kind: string;
  error_message: string;
  checked_at: string;
}

export interface ServiceHealth {
  service: Service;
  results: HealthResult[];
  availability: number | null;
  p95_latency_ms: number | null;
}

export type Severity = "debug" | "info" | "warning" | "error" | "critical";

export interface LogEvent {
  id: string;
  service_id: string | null;
  service_name: string | null;
  environment: string;
  severity: Severity;
  message: string;
  event_timestamp: string;
  received_at: string;
  attributes: Record<string, unknown>;
  redaction_count: number;
  redacted_fields: string[];
  trace_id: string | null;
  request_id: string | null;
}

export type AlertMetric = "availability" | "error_count" | "error_rate" | "latency_p95";
export type Comparator = "gt" | "gte" | "lt" | "lte";
export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "firing" | "acknowledged" | "muted" | "resolved";

export interface AlertRule {
  id: string;
  workspace_id: string;
  service_id: string | null;
  name: string;
  metric: AlertMetric;
  comparator: Comparator;
  threshold: number;
  window_seconds: number;
  dedup_window_seconds: number;
  severity: AlertSeverity;
  description: string;
  enabled: boolean;
  notify_channels: string[];
  last_evaluated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Alert {
  id: string;
  workspace_id: string;
  rule_id: string;
  rule_name: string | null;
  service_id: string | null;
  service_name: string | null;
  incident_id: string | null;
  status: AlertStatus;
  severity: AlertSeverity;
  title: string;
  description: string;
  trigger_value: number;
  threshold: number;
  window_seconds: number;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  acknowledged_at: string | null;
  muted_until: string | null;
  resolved_at: string | null;
  notified_at: string | null;
  notified_channels: string[];
  created_at: string;
}

export type IncidentStatus =
  | "open"
  | "acknowledged"
  | "investigating"
  | "mitigating"
  | "monitoring"
  | "resolved"
  | "closed";

export interface IncidentSummary {
  id: string;
  workspace_id: string;
  title: string;
  status: IncidentStatus;
  severity: AlertSeverity;
  service_id: string | null;
  service_name: string | null;
  owner_id: string | null;
  owner_label: string | null;
  detected_at: string;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentEvent {
  id: string;
  event_type: string;
  actor_id: string | null;
  actor_label: string;
  message: string;
  from_status: string;
  to_status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export type EvidenceKind =
  | "log_event"
  | "health_check_result"
  | "webhook_event"
  | "deployment"
  | "external_url"
  | "note";

export interface EvidenceLink {
  id: string;
  kind: EvidenceKind;
  ref_id: string | null;
  url: string;
  title: string;
  excerpt: string;
  metadata_json: Record<string, unknown>;
  added_by_id: string | null;
  created_at: string;
}

export interface AIAnalysisBrief {
  id: string;
  status: string;
  provider: string;
  model_id: string;
  created_at: string;
  feedback: string | null;
}

export interface IncidentDetail extends IncidentSummary {
  summary: string;
  resolution_note: string;
  follow_up_actions: Array<{ text: string; owner?: string; done?: boolean }>;
  acknowledged_at: string | null;
  events: IncidentEvent[];
  evidence: EvidenceLink[];
  alert_ids: string[];
  ai_analyses: AIAnalysisBrief[];
}

export interface Fact {
  text: string;
  citations: string[];
}

export interface Hypothesis {
  text: string;
  reasoning: string;
  confidence: "low" | "medium" | "high";
  citations: string[];
}

export interface NextCheck {
  text: string;
  rationale: string;
}

export interface AnalysisSource {
  kind: string;
  ref_id: string | null;
  url: string;
  timestamp: string;
  label: string;
}

export interface AIOutput {
  observed_facts: Fact[];
  hypotheses: Hypothesis[];
  missing_information: string[];
  recommended_next_checks: NextCheck[];
  sources?: Record<string, AnalysisSource>;
  meta?: {
    provider?: string;
    model_id?: string;
    prompt_version?: string;
    evidence_count?: number;
    instruction_markers_in_evidence?: number;
    disclaimer?: string;
  };
}

export interface AIAnalysis {
  id: string;
  incident_id: string;
  status: string;
  provider: string;
  model_id: string;
  prompt_version: string;
  evidence_ids: string[];
  output: AIOutput;
  citation_count: number;
  invalid_citations: string[];
  latency_ms: number | null;
  error: string;
  feedback: string | null;
  feedback_note: string;
  requested_by_id: string | null;
  created_at: string;
}

export interface Integration {
  id: string;
  provider: string;
  status: "pending" | "connected" | "error" | "revoked";
  external_account: string;
  external_account_id: string;
  repository_full_name: string;
  repository_id: string;
  scopes: string[];
  config: Record<string, unknown>;
  connected_at: string | null;
  revoked_at: string | null;
  last_event_at: string | null;
  last_error: string;
  created_at: string;
}

export interface WebhookEvent {
  id: string;
  provider: string;
  event_type: string;
  action: string;
  status: string;
  signature_verified: boolean;
  repository_full_name: string;
  commit_shas: string[];
  pr_number: number | null;
  deployment_ref: string;
  actor_login: string;
  occurred_at: string | null;
  received_at: string;
}

export interface DeploymentContext {
  events: WebhookEvent[];
  integrations: Integration[];
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  accepted_at: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  workspace_id: string | null;
  actor_id: string | null;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string;
  outcome: string;
  request_id: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface Report {
  id: string;
  incident_id: string;
  format: string;
  filename: string;
  size_bytes: number;
  redaction_level: string;
  generated_at: string;
}

export interface Overview {
  workspace: { id: string; name: string; timezone: string; role: Role };
  services: Record<ServiceStatus, number>;
  active_incidents: Array<{
    id: string;
    title: string;
    status: IncidentStatus;
    severity: AlertSeverity;
    detected_at: string;
  }>;
  recent_alerts: Array<{
    id: string;
    title: string;
    status: AlertStatus;
    severity: AlertSeverity;
    occurrence_count: number;
    created_at: string;
  }>;
  recent_deployments: Array<{
    id: string;
    event_type: string;
    action: string;
    repository: string;
    ref: string;
    commit_shas: string[];
    occurred_at: string | null;
  }>;
  ingestion: { events_24h: number; last_received_at: string | null; healthy: boolean };
  ai: {
    completed: number;
    failed: number;
    feedback: Record<string, number>;
    provider: string;
  };
}

export interface Notification {
  id: string;
  channel: string;
  subject: string;
  body: string;
  related_type: string;
  related_id: string;
  status: string;
  created_at: string;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface Meta {
  product: string;
  version: string;
  environment: string;
  ai_provider: string;
  ai_available: boolean;
  github_configured: boolean;
  github_webhooks_configured: boolean;
  max_log_query_range_days: number;
  max_log_batch_events: number;
  max_log_payload_bytes: number;
  allow_private_health_checks: boolean;
}
