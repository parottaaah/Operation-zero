import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { canWrite, useAuth } from "../auth/AuthContext";
import {
  Badge,
  Card,
  ConfirmDialog,
  DataTable,
  Field,
  Modal,
  PageHeader,
  Spinner,
} from "../components/ui";
import { Toasts } from "../components/Toasts";
import { useAsync } from "../hooks/useAsync";
import { useCursorPage } from "../hooks/useCursorPage";
import { useToasts } from "../hooks/useToasts";
import { api, describeError } from "../lib/api";
import { formatRelative, formatTimestamp } from "../lib/format";
import type {
  Alert,
  AlertMetric,
  AlertRule,
  AlertSeverity,
  AlertStatus,
  Comparator,
  CursorPage,
  Member,
  Service,
} from "../lib/types";

/**
 * Alert queue and the rules behind it (PRD OZ4).
 *
 * The queue is deduplicated server-side: a rule that keeps breaching inside its
 * dedup window grows `occurrence_count` instead of creating a second alert. The
 * screen shows that count explicitly so "one row" never hides a repeat problem.
 */

const STATUSES: AlertStatus[] = ["firing", "acknowledged", "muted", "resolved"];
const SEVERITIES: AlertSeverity[] = ["info", "warning", "critical"];

const METRICS: Array<{ value: AlertMetric; label: string; hint: string }> = [
  { value: "availability", label: "Availability", hint: "Ratio 0–1 of successful health checks; 0.95 means 95% up." },
  { value: "error_rate", label: "Error rate", hint: "Ratio 0–1 of error events; 0.02 means 2% of events." },
  { value: "error_count", label: "Error count", hint: "Absolute number of error events inside the window." },
  { value: "latency_p95", label: "p95 latency (ms)", hint: "95th percentile of measured latency, in milliseconds." },
];

const COMPARATORS: Array<{ value: Comparator; label: string; symbol: string }> = [
  { value: "gt", label: "greater than", symbol: ">" },
  { value: "gte", label: "at least", symbol: "≥" },
  { value: "lt", label: "less than", symbol: "<" },
  { value: "lte", label: "at most", symbol: "≤" },
];

const WINDOWS = [300, 600, 900, 1_800, 3_600];
const DEDUP_WINDOWS = [900, 1_800, 3_600, 21_600];

function formatSeconds(seconds: number): string {
  if (seconds < 3_600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3_600)}h`;
}

function comparatorSymbol(comparator: Comparator): string {
  return COMPARATORS.find((item) => item.value === comparator)?.symbol ?? comparator;
}

export default function AlertsPage() {
  const { workspace, role } = useAuth();
  const [params, setParams] = useSearchParams();
  const writable = canWrite(role, "alerts");
  const canConvert = canWrite(role, "incidents");
  const { toasts, notify } = useToasts();
  const [refreshToken, setRefreshToken] = useState(0);
  const [ruleEditor, setRuleEditor] = useState<{ mode: "create" } | { mode: "edit"; rule: AlertRule } | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<AlertRule | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [evaluating, setEvaluating] = useState(false);

  const status = (params.get("status") ?? "") as AlertStatus | "";
  const severity = (params.get("severity") ?? "") as AlertSeverity | "";

  const refresh = () => setRefreshToken((value) => value + 1);

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  const rules = useAsync<AlertRule[]>(
    (signal) => api<AlertRule[]>(`/workspaces/${workspace?.id}/alert-rules`, { signal }),
    [workspace?.id, refreshToken],
  );
  const services = useAsync<CursorPage<Service>>(
    (signal) =>
      api<CursorPage<Service>>(`/workspaces/${workspace?.id}/services?limit=200`, { signal }),
    [workspace?.id],
  );
  const members = useAsync<Member[]>(
    (signal) => api<Member[]>(`/workspaces/${workspace?.id}/members`, { signal }),
    [workspace?.id],
  );

  const evaluateNow = async () => {
    setEvaluating(true);
    try {
      const outcomes = await api<Array<{ breached: boolean; action: string }>>(
        `/workspaces/${workspace?.id}/alerts/evaluate`,
        { method: "POST" },
      );
      const breached = outcomes.filter((outcome) => outcome.breached).length;
      const created = outcomes.filter((outcome) => outcome.action === "created").length;
      notify(
        `Evaluated ${outcomes.length} rule${outcomes.length === 1 ? "" : "s"} · ${breached} breached · ${created} new alert${
          created === 1 ? "" : "s"
        }`,
      );
      refresh();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setEvaluating(false);
    }
  };

  const toggleRule = async (rule: AlertRule) => {
    try {
      await api<AlertRule>(`/workspaces/${workspace?.id}/alert-rules/${rule.id}`, {
        method: "PATCH",
        body: { enabled: !rule.enabled },
      });
      notify(`${rule.name} ${rule.enabled ? "paused" : "enabled"}`);
      rules.reload();
    } catch (cause) {
      notify(describeError(cause), "error");
    }
  };

  const deleteRule = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(`/workspaces/${workspace?.id}/alert-rules/${deleteTarget.id}`, { method: "DELETE" });
      notify(`${deleteTarget.name} deleted`);
      setDeleteTarget(null);
      rules.reload();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setDeleting(false);
    }
  };

  const serviceOptions = services.data?.items ?? [];

  return (
    <div className="page">
      <PageHeader
        title="Alerts"
        subtitle="Fired alerts, deduplication state and the rules behind them. A rule that keeps breaching inside its dedup window increments the occurrence count instead of opening another alert."
        actions={
          writable ? (
            <>
              <button type="button" className="btn" onClick={evaluateNow} disabled={evaluating}>
                {evaluating ? <Spinner /> : null}
                Evaluate now
              </button>
              <button type="button" className="btn primary" onClick={() => setRuleEditor({ mode: "create" })}>
                New rule
              </button>
            </>
          ) : (
            <Badge value="read-only role" className="plain" />
          )
        }
      />

      <Card
        title="Alert queue"
        action={
          <div className="btn-group">
            <button type="button" className="btn ghost small" onClick={refresh}>
              Refresh
            </button>
          </div>
        }
      >
        <div className="filter-bar" style={{ marginBottom: 12 }}>
          <Field label="Status">
            <select
              className="select"
              value={status}
              onChange={(event) => update({ status: event.target.value || null })}
            >
              <option value="">All statuses</option>
              {STATUSES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Severity">
            <select
              className="select"
              value={severity}
              onChange={(event) => update({ severity: event.target.value || null })}
            >
              <option value="">All severities</option>
              {SEVERITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            className="btn"
            onClick={() => update({ status: null, severity: null })}
            disabled={!status && !severity}
          >
            Clear filters
          </button>
        </div>

        <AlertQueue
          key={`${workspace?.id}|${status}|${severity}|${refreshToken}`}
          workspaceId={workspace!.id}
          writable={writable}
          canConvert={canConvert}
          members={members.data ?? []}
          onNotify={notify}
          onChanged={refresh}
        />
      </Card>

      <Card
        title="Alert rules"
        action={
          <span className="stat-hint">
            {rules.data ? `${rules.data.filter((rule) => rule.enabled).length} of ${rules.data.length} enabled` : ""}
          </span>
        }
      >
        <DataTable
          columns={[
            {
              header: "Rule",
              render: (rule) => (
                <div>
                  <strong>{rule.name}</strong>
                  <div className="stat-hint">{rule.description || "no description"}</div>
                </div>
              ),
            },
            {
              header: "Fires when",
              render: (rule) => (
                <span className="mono" style={{ fontSize: 12 }}>
                  {rule.metric} {comparatorSymbol(rule.comparator)} {rule.threshold} over{" "}
                  {formatSeconds(rule.window_seconds)}
                </span>
              ),
            },
            {
              header: "Dedup window",
              render: (rule) => formatSeconds(rule.dedup_window_seconds),
              hideSmall: true,
            },
            { header: "Severity", render: (rule) => <Badge value={rule.severity} /> },
            {
              header: "State",
              render: (rule) => <Badge value={rule.enabled ? "enabled" : "paused"} />,
            },
            {
              header: "Last evaluated",
              render: (rule) => (
                <span title={formatTimestamp(rule.last_evaluated_at)}>
                  {formatRelative(rule.last_evaluated_at)}
                </span>
              ),
              hideSmall: true,
            },
            {
              header: "",
              render: (rule) => (
                <div className="actions-cell">
                  {writable && (
                    <>
                      <button type="button" className="btn ghost small" onClick={() => toggleRule(rule)}>
                        {rule.enabled ? "Pause" : "Enable"}
                      </button>
                      <button
                        type="button"
                        className="btn ghost small"
                        onClick={() => setRuleEditor({ mode: "edit", rule })}
                      >
                        Edit
                      </button>
                      <button type="button" className="btn ghost small" onClick={() => setDeleteTarget(rule)}>
                        Delete
                      </button>
                    </>
                  )}
                </div>
              ),
            },
          ]}
          rows={rules.data}
          rowKey={(rule) => rule.id}
          loading={rules.loading}
          error={rules.error}
          onRetry={rules.reload}
          emptyTitle="No alert rules yet"
          emptyBody="A rule turns a metric threshold into a deduplicated alert. Create one to start evaluating every minute."
        />
      </Card>

      {ruleEditor && (
        <RuleModal
          workspaceId={workspace!.id}
          services={serviceOptions}
          rule={ruleEditor.mode === "edit" ? ruleEditor.rule : null}
          onClose={() => setRuleEditor(null)}
          onSaved={(message) => {
            setRuleEditor(null);
            notify(message);
            rules.reload();
          }}
          onError={(message) => notify(message, "error")}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={`Delete rule "${deleteTarget.name}"?`}
          danger
          confirmLabel="Delete rule"
          busy={deleting}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={deleteRule}
        >
          The rule stops evaluating immediately, and the alerts it fired are removed from this queue
          with it — the stored alert rows cascade with the rule. Incidents already opened from those
          alerts keep their timeline and the alert excerpt that was attached as evidence.
        </ConfirmDialog>
      )}

      <Toasts toasts={toasts} />
    </div>
  );
}

function AlertQueue({
  workspaceId,
  writable,
  canConvert,
  members,
  onNotify,
  onChanged,
}: {
  workspaceId: string;
  writable: boolean;
  canConvert: boolean;
  members: Member[];
  onNotify: (text: string, tone?: "info" | "error") => void;
  onChanged: () => void;
}) {
  const [params] = useSearchParams();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [muteTarget, setMuteTarget] = useState<Alert | null>(null);
  const [convertTarget, setConvertTarget] = useState<Alert | null>(null);
  const [resolveTarget, setResolveTarget] = useState<Alert | null>(null);

  const queue = useCursorPage<Alert>((cursor, signal) => {
    const query = new URLSearchParams({ limit: "25" });
    const status = params.get("status");
    const severity = params.get("severity");
    if (status) query.set("status", status);
    if (severity) query.set("severity", severity);
    if (cursor) query.set("cursor", cursor);
    return api<CursorPage<Alert>>(`/workspaces/${workspaceId}/alerts?${query}`, { signal });
  });

  const act = async (alert: Alert, work: () => Promise<unknown>, message: string) => {
    setBusyId(alert.id);
    try {
      await work();
      onNotify(message);
      onChanged();
    } catch (cause) {
      onNotify(describeError(cause), "error");
    } finally {
      setBusyId(null);
    }
  };

  const items = queue.items;

  return (
    <>
      <DataTable
        columns={[
          {
            header: "Alert",
            render: (alert) => (
              <div>
                <strong>{alert.title}</strong>
                <div className="stat-hint">
                  {alert.rule_name ?? "rule removed"}
                  {alert.incident_id && (
                    <>
                      {" · "}
                      <Link to={`/incidents/${alert.incident_id}`}>linked incident</Link>
                    </>
                  )}
                </div>
              </div>
            ),
          },
          { header: "Severity", render: (alert) => <Badge value={alert.severity} /> },
          {
            header: "Service",
            render: (alert) => alert.service_name ?? <span className="stat-hint">workspace</span>,
          },
          {
            header: "Trigger",
            render: (alert) => (
              <span className="mono" style={{ fontSize: 12 }}>
                {alert.trigger_value} vs {alert.threshold} / {formatSeconds(alert.window_seconds)}
              </span>
            ),
            hideSmall: true,
          },
          {
            header: "Occurrences",
            numeric: true,
            render: (alert) =>
              alert.occurrence_count > 1 ? (
                <Badge value={`×${alert.occurrence_count}`} className="plain" />
              ) : (
                <span className="stat-hint">1</span>
              ),
          },
          {
            header: "Last seen",
            render: (alert) => (
              <span title={formatTimestamp(alert.last_seen_at)}>{formatRelative(alert.last_seen_at)}</span>
            ),
          },
          { header: "Status", render: (alert) => <Badge value={alert.status} /> },
          {
            header: "",
            render: (alert) => (
              <div className="actions-cell">
                {busyId === alert.id ? (
                  <Spinner />
                ) : writable ? (
                  <>
                    {alert.status !== "acknowledged" && alert.status !== "resolved" && (
                      <button
                        type="button"
                        className="btn ghost small"
                        onClick={() =>
                          act(
                            alert,
                            () =>
                              api(`/workspaces/${workspaceId}/alerts/${alert.id}/acknowledge`, {
                                method: "POST",
                                body: { note: "" },
                              }),
                            "Alert acknowledged",
                          )
                        }
                      >
                        Acknowledge
                      </button>
                    )}
                    {alert.status !== "muted" && alert.status !== "resolved" && (
                      <button type="button" className="btn ghost small" onClick={() => setMuteTarget(alert)}>
                        Mute
                      </button>
                    )}
                    {alert.status !== "resolved" && (
                      <button type="button" className="btn ghost small" onClick={() => setResolveTarget(alert)}>
                        Resolve
                      </button>
                    )}
                    {!alert.incident_id && canConvert && (
                      <button type="button" className="btn ghost small" onClick={() => setConvertTarget(alert)}>
                        To incident
                      </button>
                    )}
                  </>
                ) : null}
              </div>
            ),
          },
        ]}
        rows={items}
        rowKey={(alert) => alert.id}
        loading={queue.loading}
        error={queue.error}
        onRetry={queue.reload}
        emptyTitle="No alerts in this view"
        emptyBody="Adjust the status or severity filter. Rules only fire when their metric actually breaches."
      />

      <div className="pagination">
        <div className="btn-group">
          <button type="button" className="btn" onClick={queue.goNewer} disabled={!queue.hasNewer || queue.loading}>
            ← Newer
          </button>
          <button type="button" className="btn" onClick={queue.goOlder} disabled={!queue.hasOlder || queue.loading}>
            Older →
          </button>
        </div>
      </div>

      {muteTarget && (
        <MuteModal
          workspaceId={workspaceId}
          alert={muteTarget}
          onClose={() => setMuteTarget(null)}
          onDone={(message) => {
            setMuteTarget(null);
            onNotify(message);
            onChanged();
          }}
          onError={(message) => onNotify(message, "error")}
        />
      )}

      {convertTarget && (
        <ConvertModal
          workspaceId={workspaceId}
          alert={convertTarget}
          members={members}
          onClose={() => setConvertTarget(null)}
          onDone={(message) => {
            setConvertTarget(null);
            onNotify(message);
            onChanged();
          }}
          onError={(message) => onNotify(message, "error")}
        />
      )}

      {resolveTarget && (
        <ConfirmDialog
          title="Resolve this alert?"
          confirmLabel="Resolve"
          onCancel={() => setResolveTarget(null)}
          onConfirm={() => {
            const alert = resolveTarget;
            setResolveTarget(null);
            void act(
              alert,
              () => api(`/workspaces/${workspaceId}/alerts/${alert.id}/resolve`, { method: "POST" }),
              "Alert resolved",
            );
          }}
        >
          Resolving closes this row and stops further notifications for it. The triggering rule keeps
          evaluating and can fire a new alert on the next breach.
        </ConfirmDialog>
      )}
    </>
  );
}

function MuteModal({
  workspaceId,
  alert,
  onClose,
  onDone,
  onError,
}: {
  workspaceId: string;
  alert: Alert;
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [minutes, setMinutes] = useState("60");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/alerts/${alert.id}/mute`, {
        method: "POST",
        body: { duration_minutes: Number(minutes), reason },
      });
      onDone(`Muted for ${formatSeconds(Number(minutes) * 60)}`);
    } catch (cause) {
      onError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Mute "${alert.title}"`} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <p className="stat-hint" style={{ margin: 0 }}>
          Muting suppresses notifications for this alert only. The underlying rule and its metrics keep
          running, so a real outage is never hidden from the rules list.
        </p>
        <div className="form-grid">
          <Field label="Duration">
            <select className="select" value={minutes} onChange={(event) => setMinutes(event.target.value)}>
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="60">1 hour</option>
              <option value="240">4 hours</option>
              <option value="1440">24 hours</option>
            </select>
          </Field>
          <Field label="Reason (recorded in the audit trail)">
            <input
              className="input"
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="known noisy during backfill"
            />
          </Field>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? <Spinner /> : null}
            Mute alert
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ConvertModal({
  workspaceId,
  alert,
  members,
  onClose,
  onDone,
  onError,
}: {
  workspaceId: string;
  alert: Alert;
  members: Member[];
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [title, setTitle] = useState(
    alert.service_name ? `${alert.title} · ${alert.service_name}` : alert.title,
  );
  const [severity, setSeverity] = useState<AlertSeverity>(alert.severity);
  const [summary, setSummary] = useState(alert.description);
  const [ownerId, setOwnerId] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/alerts/${alert.id}/to-incident`, {
        method: "POST",
        body: {
          title,
          summary,
          severity,
          owner_id: ownerId || null,
        },
      });
      onDone("Incident opened from alert");
    } catch (cause) {
      onError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Convert alert to incident" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <p className="stat-hint" style={{ margin: 0 }}>
          The alert is attached to the new incident as evidence and stays linked. Nothing about the
          incident's severity or cause is inferred from the alert alone — that still needs a human.
        </p>
        <Field label="Incident title">
          <input
            className="input"
            required
            maxLength={240}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label="Severity">
            <select
              className="select"
              value={severity}
              onChange={(event) => setSeverity(event.target.value as AlertSeverity)}
            >
              {SEVERITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Owner" hint="Optional. Only workspace members can own an incident.">
            <select className="select" value={ownerId} onChange={(event) => setOwnerId(event.target.value)}>
              <option value="">Unassigned</option>
              {members.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.full_name} ({member.role})
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Summary">
          <textarea
            className="textarea"
            value={summary}
            maxLength={8000}
            onChange={(event) => setSummary(event.target.value)}
          />
        </Field>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? <Spinner /> : null}
            Open incident
          </button>
        </div>
      </form>
    </Modal>
  );
}

function RuleModal({
  workspaceId,
  services,
  rule,
  onClose,
  onSaved,
  onError,
}: {
  workspaceId: string;
  services: Service[];
  rule: AlertRule | null;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [metric, setMetric] = useState<AlertMetric>(rule?.metric ?? "error_rate");
  const [comparator, setComparator] = useState<Comparator>(rule?.comparator ?? "gt");
  const [threshold, setThreshold] = useState(String(rule?.threshold ?? 0.02));
  const [serviceId, setServiceId] = useState(rule?.service_id ?? "");
  const [windowSeconds, setWindowSeconds] = useState(String(rule?.window_seconds ?? 300));
  const [dedupSeconds, setDedupSeconds] = useState(String(rule?.dedup_window_seconds ?? 1_800));
  const [severity, setSeverity] = useState<AlertSeverity>(rule?.severity ?? "warning");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [channels, setChannels] = useState<string[]>(rule?.notify_channels ?? ["in_app"]);
  const [busy, setBusy] = useState(false);

  const metricSpec = METRICS.find((item) => item.value === metric);
  const ratioMetric = metric === "availability" || metric === "error_rate";

  const toggleChannel = (channel: string) => {
    setChannels((current) =>
      current.includes(channel) ? current.filter((item) => item !== channel) : [...current, channel],
    );
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const payload = {
      name,
      metric,
      comparator,
      threshold: Number(threshold),
      service_id: serviceId || null,
      window_seconds: Number(windowSeconds),
      dedup_window_seconds: Number(dedupSeconds),
      severity,
      description,
      enabled,
      notify_channels: channels,
    };
    try {
      if (rule) {
        await api(`/workspaces/${workspaceId}/alert-rules/${rule.id}`, { method: "PATCH", body: payload });
        onSaved(`${name} updated`);
      } else {
        await api(`/workspaces/${workspaceId}/alert-rules`, { method: "POST", body: payload });
        onSaved(`${name} created`);
      }
    } catch (cause) {
      onError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={rule ? `Edit "${rule.name}"` : "New alert rule"} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <Field label="Rule name">
          <input
            className="input"
            required
            maxLength={160}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Checkout error rate above 2%"
          />
        </Field>
        <div className="form-grid">
          <Field label="Metric" hint={metricSpec?.hint}>
            <select
              className="select"
              value={metric}
              onChange={(event) => setMetric(event.target.value as AlertMetric)}
            >
              {METRICS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Comparison">
            <select
              className="select"
              value={comparator}
              onChange={(event) => setComparator(event.target.value as Comparator)}
            >
              {COMPARATORS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label} ({option.symbol})
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Threshold"
            hint={ratioMetric ? "Ratio between 0 and 1 — 0.02 is 2%." : "Absolute value in the metric's unit."}
          >
            <input
              className="input mono"
              type="number"
              required
              min={0}
              max={ratioMetric ? 1 : undefined}
              step={ratioMetric ? 0.01 : 1}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </Field>
          <Field label="Service" hint="Workspace-wide rules apply to every service.">
            <select className="select" value={serviceId} onChange={(event) => setServiceId(event.target.value)}>
              <option value="">Whole workspace</option>
              {services.map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Evaluation window">
            <select className="select" value={windowSeconds} onChange={(event) => setWindowSeconds(event.target.value)}>
              {WINDOWS.map((option) => (
                <option key={option} value={option}>
                  {formatSeconds(option)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Dedup window" hint="Repeat breaches inside this window increment the alert.">
            <select className="select" value={dedupSeconds} onChange={(event) => setDedupSeconds(event.target.value)}>
              {DEDUP_WINDOWS.map((option) => (
                <option key={option} value={option}>
                  {formatSeconds(option)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Severity">
            <select
              className="select"
              value={severity}
              onChange={(event) => setSeverity(event.target.value as AlertSeverity)}
            >
              {SEVERITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Description" hint="Shown in the alert queue and copied into a converted incident.">
          <textarea
            className="textarea"
            maxLength={2000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <div className="form-grid">
          <div className="field">
            <label>Notifications</label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={channels.includes("in_app")}
                onChange={() => toggleChannel("in_app")}
              />
              In-app notification
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={channels.includes("email")}
                onChange={() => toggleChannel("email")}
              />
              Email (only if SMTP is configured)
            </label>
            {channels.length === 0 && (
              <span className="hint" style={{ color: "var(--danger)" }}>
                At least one channel is required.
              </span>
            )}
          </div>
          <div className="field">
            <label>State</label>
            <label className="checkbox-row">
              <input type="checkbox" checked={enabled} onChange={() => setEnabled((value) => !value)} />
              Evaluate this rule
            </label>
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy || channels.length === 0}>
            {busy ? <Spinner /> : null}
            {rule ? "Save changes" : "Create rule"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
