import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { canWrite, useAuth } from "../auth/AuthContext";
import {
  Badge,
  Card,
  DataTable,
  Field,
  Modal,
  PageHeader,
  Spinner,
} from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useCursorPage } from "../hooks/useCursorPage";
import { api, describeError } from "../lib/api";
import { formatRelative, formatTimestamp } from "../lib/format";
import type {
  AlertSeverity,
  CursorPage,
  IncidentDetail,
  IncidentStatus,
  IncidentSummary,
  Member,
  Service,
} from "../lib/types";

/**
 * Incident queue (PRD OZ5).
 *
 * Triage view: filter by lifecycle state, jump straight into the incident room.
 * Rows are keyboard reachable (Tab to a row, Arrow keys to move, Enter to open).
 */

const STATUSES: IncidentStatus[] = [
  "open",
  "acknowledged",
  "investigating",
  "mitigating",
  "monitoring",
  "resolved",
  "closed",
];
const SEVERITIES: AlertSeverity[] = ["info", "warning", "critical"];

export default function IncidentsPage() {
  const { workspace, role } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const writable = canWrite(role, "incidents");
  const [creating, setCreating] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const status = (params.get("status") ?? "") as IncidentStatus | "";
  const severity = (params.get("severity") ?? "") as AlertSeverity | "";
  const serviceId = params.get("service") ?? "";
  const query = params.get("q") ?? "";

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  const services = useAsync<CursorPage<Service>>(
    (signal) =>
      api<CursorPage<Service>>(`/workspaces/${workspace?.id}/services?limit=200`, { signal }),
    [workspace?.id],
  );
  const members = useAsync<Member[]>(
    (signal) => api<Member[]>(`/workspaces/${workspace?.id}/members`, { signal }),
    [workspace?.id],
  );

  const filterSignature = [workspace?.id, status, severity, serviceId, query, refreshToken].join("|");

  return (
    <div className="page">
      <PageHeader
        title="Incidents"
        subtitle="Every incident with its owner, severity and current lifecycle state. Status changes are validated server-side — open → acknowledged → investigating → mitigating → monitoring → resolved → closed, with the legal backward moves."
        actions={
          writable ? (
            <button type="button" className="btn primary" onClick={() => setCreating(true)}>
              Open incident
            </button>
          ) : (
            <Badge value="read-only role" className="plain" />
          )
        }
      />

      <Card>
        <form
          className="filter-bar"
          style={{ marginBottom: 12 }}
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            update({ q: String(data.get("q") ?? "").trim() || null });
          }}
        >
          <Field label="Status">
            <select
              className="select"
              value={status}
              onChange={(event) => update({ status: event.target.value || null })}
            >
              <option value="">All states</option>
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
          <Field label="Service">
            <select
              className="select"
              value={serviceId}
              onChange={(event) => update({ service: event.target.value || null })}
            >
              <option value="">All services</option>
              {(services.data?.items ?? []).map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Title contains" full>
            <input
              key={query}
              className="input"
              name="q"
              defaultValue={query}
              maxLength={120}
              placeholder="checkout"
            />
          </Field>
          <div className="btn-group">
            <button type="submit" className="btn">
              Search
            </button>
            <button
              type="button"
              className="btn ghost"
              onClick={() => update({ status: null, severity: null, service: null, q: null })}
            >
              Clear
            </button>
            <button type="button" className="btn ghost" onClick={() => setRefreshToken((value) => value + 1)}>
              Refresh
            </button>
          </div>
        </form>

        <IncidentQueue
          key={filterSignature}
          workspaceId={workspace!.id}
          onOpen={(incident) => navigate(`/incidents/${incident.id}`)}
        />
      </Card>

      {creating && (
        <CreateIncidentModal
          workspaceId={workspace!.id}
          services={services.data?.items ?? []}
          members={members.data ?? []}
          onClose={() => setCreating(false)}
          onCreated={(incident) => {
            setCreating(false);
            navigate(`/incidents/${incident.id}`);
          }}
        />
      )}
    </div>
  );
}

function IncidentQueue({
  workspaceId,
  onOpen,
}: {
  workspaceId: string;
  onOpen: (incident: IncidentSummary) => void;
}) {
  const [params] = useSearchParams();

  const queue = useCursorPage<IncidentSummary>((cursor, signal) => {
    const query = new URLSearchParams({ limit: "25" });
    const status = params.get("status");
    const severity = params.get("severity");
    const service = params.get("service");
    const q = params.get("q");
    if (status) query.set("status", status);
    if (severity) query.set("severity", severity);
    if (service) query.set("service_id", service);
    if (q) query.set("q", q);
    if (cursor) query.set("cursor", cursor);
    return api<CursorPage<IncidentSummary>>(`/workspaces/${workspaceId}/incidents?${query}`, {
      signal,
    });
  });

  return (
    <>
      <DataTable
        columns={[
          {
            header: "Incident",
            render: (row) => (
              <div>
                <strong>{row.title}</strong>
                <div className="stat-hint">{row.service_name ?? "workspace-wide"}</div>
              </div>
            ),
          },
          { header: "Severity", render: (row) => <Badge value={row.severity} /> },
          { header: "Status", render: (row) => <Badge value={row.status} /> },
          {
            header: "Owner",
            render: (row) => row.owner_label ?? <span className="stat-hint">unassigned</span>,
          },
          {
            header: "Detected",
            render: (row) => (
              <span title={formatTimestamp(row.detected_at)}>{formatRelative(row.detected_at)}</span>
            ),
          },
          {
            header: "Resolved",
            render: (row) =>
              row.resolved_at ? (
                <span title={formatTimestamp(row.resolved_at)}>{formatRelative(row.resolved_at)}</span>
              ) : (
                <span className="stat-hint">—</span>
              ),
            hideSmall: true,
          },
        ]}
        rows={queue.items}
        rowKey={(row) => row.id}
        loading={queue.loading}
        error={queue.error}
        onRetry={queue.reload}
        onRowClick={onOpen}
        emptyTitle="No incidents in this view"
        emptyBody="Adjust the filters, or open an incident if something is already going on."
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
    </>
  );
}

function CreateIncidentModal({
  workspaceId,
  services,
  members,
  onClose,
  onCreated,
}: {
  workspaceId: string;
  services: Service[];
  members: Member[];
  onClose: () => void;
  onCreated: (incident: IncidentDetail) => void;
}) {
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [severity, setSeverity] = useState<AlertSeverity>("warning");
  const [serviceId, setServiceId] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const incident = await api<IncidentDetail>(`/workspaces/${workspaceId}/incidents`, {
        method: "POST",
        body: {
          title,
          summary,
          severity,
          service_id: serviceId || null,
          owner_id: ownerId || null,
        },
      });
      onCreated(incident);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Open an incident" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        {error && <div className="notice error">{error}</div>}
        <Field label="Title" hint="What is broken, in the words the responder would use.">
          <input
            className="input"
            required
            minLength={3}
            maxLength={240}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Checkout p99 above 4s in production"
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
          <Field label="Service" hint="Leave empty for a workspace-wide incident.">
            <select className="select" value={serviceId} onChange={(event) => setServiceId(event.target.value)}>
              <option value="">Workspace-wide</option>
              {services.map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Owner" hint="Can be assigned later; ownership changes are on the timeline.">
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
        <Field label="Summary" hint="What is observed so far. Hypotheses belong in the AI panel, not here.">
          <textarea
            className="textarea"
            maxLength={8000}
            value={summary}
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
