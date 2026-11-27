import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { canReadRawTelemetry, useAuth } from "../auth/AuthContext";
import {
  Badge,
  Card,
  DataTable,
  EmptyState,
  Field,
  LoadingBlock,
  Notice,
  PageHeader,
} from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useCursorPage } from "../hooks/useCursorPage";
import { api } from "../lib/api";
import { formatTimestamp, truncate } from "../lib/format";
import type { CursorPage, LogEvent, Meta, Service } from "../lib/types";

/**
 * Log explorer (PRD OZ3).
 *
 * Every filter lives in the URL so a view can be pasted into an incident timeline.
 * Queries are bounded to the server-side maximum range and pushed through keyset
 * pagination — there is no free-form query language and no unbounded scan.
 */
const PRESETS = [
  { value: "15m", label: "Last 15 minutes", minutes: 15 },
  { value: "1h", label: "Last hour", minutes: 60 },
  { value: "6h", label: "Last 6 hours", minutes: 360 },
  { value: "24h", label: "Last 24 hours", minutes: 1_440 },
  { value: "7d", label: "Last 7 days", minutes: 10_080 },
] as const;

const DEFAULT_RANGE = "24h";
const PAGE_SIZE = 50;

const SEVERITIES = ["debug", "info", "warning", "error", "critical"] as const;
const ENVIRONMENTS = ["production", "staging", "development"] as const;

export default function LogsPage() {
  const { workspace, role } = useAuth();
  const [params, setParams] = useSearchParams();
  const [refreshToken, setRefreshToken] = useState(0);

  const meta = useAsync<Meta>((signal) => api<Meta>("/meta", { signal }), []);
  const maxRangeDays = meta.data?.max_log_query_range_days ?? 7;
  const maxRangeMinutes = maxRangeDays * 1_440;
  const allowedPresets = PRESETS.filter((option) => option.minutes <= maxRangeMinutes);
  const usablePresets = allowedPresets.length > 0 ? allowedPresets : PRESETS.slice(0, 1);

  const requestedRange = params.get("range") ?? DEFAULT_RANGE;
  const preset =
    usablePresets.find((candidate) => candidate.value === requestedRange) ??
    usablePresets[usablePresets.length - 1];
  const severity = params.get("severity") ?? "";
  const serviceId = params.get("service") ?? "";
  const environment = params.get("environment") ?? "";
  const query = params.get("q") ?? "";
  const selectedId = params.get("event");

  const services = useAsync<CursorPage<Service>>(
    (signal) =>
      api<CursorPage<Service>>(`/workspaces/${workspace?.id}/services?limit=200`, { signal }),
    [workspace?.id],
  );

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  if (!canReadRawTelemetry(role)) {
    return (
      <div className="page">
        <PageHeader
          title="Logs"
          subtitle="Bounded, redacted log exploration for one workspace."
        />
        <Notice tone="warn">
          Reading raw telemetry requires an engineer, admin, owner or security-analyst role. A
          viewer can follow incident summaries and reports, but not the underlying log events. This
          is enforced by the API as well as this screen.
        </Notice>
      </div>
    );
  }

  const filterSignature = [
    workspace?.id,
    preset.value,
    severity,
    serviceId,
    environment,
    query,
    refreshToken,
  ].join("|");

  return (
    <div className="page">
      <PageHeader
        title="Logs"
        subtitle={`Redacted structured events, newest first. Queries are limited to ${
          maxRangeDays >= 1 ? `${maxRangeDays} day${maxRangeDays === 1 ? "" : "s"}` : "the configured window"
        } and every filter is stored in the URL.`}
        actions={
          <div className="btn-group">
            <button
              type="button"
              className="btn"
              onClick={() => update({ event: null })}
              disabled={!selectedId}
            >
              Clear selection
            </button>
            <button type="button" className="btn" onClick={() => setRefreshToken((value) => value + 1)}>
              Refresh
            </button>
          </div>
        }
      />

      <Card>
        <form
          className="filter-bar"
          style={{ marginBottom: 12 }}
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            update({ q: String(data.get("q") ?? "").trim() || null, event: null });
          }}
        >
          <Field label="Time range">
            <select
              className="select"
              value={preset.value}
              onChange={(event) => update({ range: event.target.value, event: null })}
            >
              {usablePresets.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Severity">
            <select
              className="select"
              value={severity}
              onChange={(event) => update({ severity: event.target.value || null, event: null })}
            >
              <option value="">All severities</option>
              {SEVERITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Service">
            <select
              className="select"
              value={serviceId}
              onChange={(event) => update({ service: event.target.value || null, event: null })}
            >
              <option value="">All services</option>
              {(services.data?.items ?? []).map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Environment">
            <select
              className="select"
              value={environment}
              onChange={(event) => update({ environment: event.target.value || null, event: null })}
            >
              <option value="">All environments</option>
              {ENVIRONMENTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Message contains" hint="Case-insensitive substring match." full>
            <input
              key={query}
              className="input"
              name="q"
              defaultValue={query}
              maxLength={200}
              placeholder="connection refused"
            />
          </Field>
          <div className="btn-group">
            <button type="submit" className="btn primary">
              Apply
            </button>
            <button
              type="button"
              className="btn"
              onClick={() =>
                update({
                  severity: null,
                  service: null,
                  environment: null,
                  q: null,
                  event: null,
                })
              }
            >
              Clear filters
            </button>
          </div>
        </form>

        <LogResults
          key={filterSignature}
          workspaceId={workspace!.id}
          workspaceTimezone={workspace?.timezone ?? null}
          rangeMinutes={preset.minutes}
          severity={severity}
          serviceId={serviceId}
          environment={environment}
          query={query}
          selectedId={selectedId}
          onSelect={(id) => update({ event: id })}
        />
      </Card>
    </div>
  );
}

function LogResults({
  workspaceId,
  workspaceTimezone,
  rangeMinutes,
  severity,
  serviceId,
  environment,
  query,
  selectedId,
  onSelect,
}: {
  workspaceId: string;
  workspaceTimezone: string | null;
  rangeMinutes: number;
  severity: string;
  serviceId: string;
  environment: string;
  query: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  // Frozen at mount: the parent remounts this component whenever a filter or the
  // refresh token changes, so a page of results always describes one fixed window.
  const windowRange = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - rangeMinutes * 60_000);
    return { from, to };
  }, [rangeMinutes]);

  const logs = useCursorPage<LogEvent>((cursor, signal) => {
    const params = new URLSearchParams({
      from_ts: windowRange.from.toISOString(),
      to_ts: windowRange.to.toISOString(),
      limit: String(PAGE_SIZE),
    });
    if (severity) params.set("severity", severity);
    if (serviceId) params.set("service_id", serviceId);
    if (environment) params.set("environment", environment);
    if (query) params.set("q", query);
    if (cursor) params.set("cursor", cursor);
    return api<CursorPage<LogEvent>>(`/workspaces/${workspaceId}/logs?${params}`, { signal });
  });

  const items = logs.items;
  const selected = items?.find((item) => item.id === selectedId) ?? null;

  return (
    <>
      <div className="log-detail">
        <div>
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <span className="stat-label" aria-live="polite">
              {items === null
                ? "Loading events…"
                : `${items.length} event${items.length === 1 ? "" : "s"} on page ${logs.pageNumber}`}
            </span>
            <span className="stat-hint mono">
              {formatTimestamp(windowRange.from.toISOString())} → {formatTimestamp(windowRange.to.toISOString())}
            </span>
          </div>
          <p className="stat-hint" style={{ margin: "0 0 10px" }}>
            Times render in your browser timezone. Workspace timezone: {workspaceTimezone ?? "not set"}.
          </p>

          <DataTable
            columns={[
              {
                header: "Time",
                render: (row) => (
                  <span className="mono" style={{ fontSize: 12 }} title={row.event_timestamp}>
                    {formatTimestamp(row.event_timestamp)}
                  </span>
                ),
              },
              { header: "Severity", render: (row) => <Badge value={row.severity} /> },
              {
                header: "Service",
                render: (row) => row.service_name ?? <span className="stat-hint">unattributed</span>,
              },
              {
                header: "Message",
                render: (row) => <span className="mono">{truncate(row.message, 110)}</span>,
              },
              {
                header: "Redacted",
                numeric: true,
                render: (row) =>
                  row.redaction_count > 0 ? (
                    <Badge value={`${row.redaction_count} fields`} className="plain" />
                  ) : (
                    <span className="stat-hint">none</span>
                  ),
                hideSmall: true,
              },
            ]}
            rows={items}
            rowKey={(row) => row.id}
            loading={logs.loading}
            error={logs.error}
            onRetry={logs.reload}
            onRowClick={(row) => onSelect(row.id === selectedId ? null : row.id)}
            selectedKey={selectedId}
            rowClassName={(row) => `log-row ${row.severity === "error" || row.severity === "critical" ? row.severity : ""}`}
            emptyTitle="No events in this window"
            emptyBody="Widen the time range, clear a filter, or send events to this workspace's ingestion endpoint."
          />

          <div className="pagination">
            <div className="btn-group">
              <button type="button" className="btn" onClick={logs.goNewer} disabled={!logs.hasNewer || logs.loading}>
                ← Newer
              </button>
              <button type="button" className="btn" onClick={logs.goOlder} disabled={!logs.hasOlder || logs.loading}>
                Older →
              </button>
            </div>
          </div>
        </div>

        <div>
          {logs.error && !items ? (
            <Card title="Event detail">
              <p className="stat-hint" style={{ margin: 0 }}>
                The event list failed to load, so no event can be selected yet.
              </p>
            </Card>
          ) : logs.loading && !items ? (
            <Card title="Event detail">
              <LoadingBlock lines={4} />
            </Card>
          ) : selected ? (
            <LogDetail event={selected} onClose={() => onSelect(null)} />
          ) : (
            <Card title="Event detail">
              <EmptyState title={selectedId ? "Event not on this page" : "No event selected"}>
                {selectedId
                  ? "The linked event is outside the current page or window. Widen the time range or clear filters, then select it again."
                  : "Select a row to inspect the full message, identifiers, attributes and redaction metadata."}
              </EmptyState>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function LogDetail({ event, onClose }: { event: LogEvent; onClose: () => void }) {
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (label: string, value: string) => {
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(label);
        window.setTimeout(() => setCopied((current) => (current === label ? null : current)), 2_000);
      })
      .catch(() => setCopied(null));
  };

  const eventJson = JSON.stringify(event, null, 2);

  return (
    <Card
      title="Event detail"
      action={
        <div className="btn-group">
          <button type="button" className="btn ghost small" onClick={() => copy("json", eventJson)}>
            {copied === "json" ? "Copied" : "Copy JSON"}
          </button>
          <button type="button" className="btn ghost small" onClick={() => copy("link", window.location.href)}>
            {copied === "link" ? "Copied" : "Copy link"}
          </button>
          <button type="button" className="btn ghost small" onClick={onClose}>
            Close
          </button>
        </div>
      }
    >
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <Badge value={event.severity} />
        <Badge value={event.environment} className="plain" />
        {event.redaction_count > 0 && (
          <Badge value={`${event.redaction_count} redacted`} className="plain" />
        )}
      </div>

      <pre className="mono" style={{ margin: "0 0 12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {event.message}
      </pre>

      <dl className="kv">
        <dt>Event time</dt>
        <dd>{formatTimestamp(event.event_timestamp)}</dd>
        <dt>Received</dt>
        <dd>{formatTimestamp(event.received_at)}</dd>
        <dt>Service</dt>
        <dd>{event.service_name ?? "—"}</dd>
        <dt>Event ID</dt>
        <dd>{event.id}</dd>
        <dt>Trace ID</dt>
        <dd>{event.trace_id ?? "—"}</dd>
        <dt>Request ID</dt>
        <dd>{event.request_id ?? "—"}</dd>
      </dl>

      <div className="divider" />

      <div className="ai-section">
        <h4>Redaction</h4>
        {event.redaction_count === 0 ? (
          <p className="stat-hint" style={{ margin: 0 }}>
            No sensitive values were detected in this event.
          </p>
        ) : (
          <>
            <p className="stat-hint" style={{ marginTop: 0 }}>
              {event.redaction_count} sensitive value{event.redaction_count === 1 ? "" : "s"} masked
              before persistence. Only the field paths are stored, never the original values.
            </p>
            <div className="citations">
              {event.redacted_fields.map((field) => (
                <span key={field} className="citation">
                  {field}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="ai-section">
        <h4>Attributes</h4>
        {Object.keys(event.attributes).length === 0 ? (
          <p className="stat-hint" style={{ margin: 0 }}>
            This event carried no extra attributes.
          </p>
        ) : (
          <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12 }}>
            {JSON.stringify(event.attributes, null, 2)}
          </pre>
        )}
      </div>
    </Card>
  );
}
