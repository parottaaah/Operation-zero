import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { canWrite, useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { api, describeError } from "../lib/api";
import { formatRelative, formatTimestamp } from "../lib/format";
import type { CursorPage, Environment, Service, ServiceCreated } from "../lib/types";
import {
  Badge,
  Card,
  DataTable,
  Field,
  Modal,
  Notice,
  PageHeader,
  Spinner,
} from "../components/ui";

export default function ServicesPage() {
  const { workspace, role } = useAuth();
  const navigate = useNavigate();
  const [environment, setEnvironment] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ServiceCreated | null>(null);
  const [error, setError] = useState<string | null>(null);

  const services = useAsync<CursorPage<Service>>((signal) => {
    const params = new URLSearchParams({ limit: "100" });
    if (environment) params.set("environment", environment);
    if (status) params.set("status", status);
    if (query) params.set("q", query);
    return api<CursorPage<Service>>(`/workspaces/${workspace?.id}/services?${params}`, { signal });
  }, [workspace?.id, environment, status, query]);

  return (
    <div className="page">
      <PageHeader
        title="Services"
        subtitle="Registered services, their environments and HTTP health state. Health checks block private network ranges by default to prevent SSRF."
        actions={
          canWrite(role, "services") ? (
            <button type="button" className="btn primary" onClick={() => setCreating(true)}>
              Register service
            </button>
          ) : (
            <Badge value="read-only role" className="plain" />
          )
        }
      />

      {error && <Notice tone="error">{error}</Notice>}

      <Card>
        <div className="filter-bar" style={{ marginBottom: 12 }}>
          <Field label="Environment">
            <select
              className="select"
              value={environment}
              onChange={(event) => setEnvironment(event.target.value)}
            >
              <option value="">All environments</option>
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="development">development</option>
            </select>
          </Field>
          <Field label="Status">
            <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">All statuses</option>
              <option value="healthy">healthy</option>
              <option value="degraded">degraded</option>
              <option value="down">down</option>
              <option value="unknown">unknown</option>
              <option value="paused">paused</option>
            </select>
          </Field>
          <Field label="Search" >
            <input
              className="input"
              placeholder="Name contains…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Field>
          <button type="button" className="btn" onClick={services.reload}>
            Refresh
          </button>
        </div>

        <DataTable
          columns={[
            {
              header: "Service",
              render: (row) => (
                <div>
                  <strong>{row.name}</strong>
                  <div className="stat-hint">
                    {row.owner_team || "no owner team"} · key …{row.ingestion_key_last4}
                  </div>
                </div>
              ),
            },
            { header: "Environment", render: (row) => <Badge value={row.environment} /> },
            { header: "Status", render: (row) => <Badge value={row.status} /> },
            {
              header: "Last checked",
              render: (row) => (
                <span title={formatTimestamp(row.last_checked_at)}>
                  {formatRelative(row.last_checked_at)}
                </span>
              ),
            },
            {
              header: "Health check",
              render: (row) =>
                row.health_check ? (
                  <span className="mono" style={{ fontSize: 11.5 }}>
                    {row.health_check.method} {new URL(row.health_check.url).pathname} ·{" "}
                    {row.health_check.interval_seconds}s
                  </span>
                ) : (
                  <span style={{ color: "var(--subtle)" }}>not configured</span>
                ),
              hideSmall: true,
            },
          ]}
          rows={services.data?.items ?? null}
          rowKey={(row) => row.id}
          loading={services.loading}
          error={services.error}
          onRetry={services.reload}
          emptyTitle="No services registered"
          emptyBody="Register a service to get an ingestion key and an HTTP health check."
          onRowClick={(row) => navigate(`/services/${row.id}`)}
        />
      </Card>

      {creating && (
        <CreateServiceModal
          workspaceId={workspace!.id}
          onClose={() => setCreating(false)}
          onCreated={(service) => {
            setCreating(false);
            setCreated(service);
            services.reload();
          }}
          onError={setError}
        />
      )}

      {created && (
        <Modal title="Service created" onClose={() => setCreated(null)}>
          <Notice tone="info">
            Copy the ingestion key now. It is stored only as a hash and cannot be shown again.
          </Notice>
          <div className="stack" style={{ marginTop: 12 }}>
            <Field label="Ingestion key">
              <input className="input mono" readOnly value={created.ingestion_key} />
            </Field>
            <Field label="Send a first log event">
              <pre>{`curl -X POST ${window.location.origin.replace(":5173", ":8000")}/api/v1/ingest/logs \\
  -H "X-Ingestion-Key: ${created.ingestion_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"events":[{"message":"deploy check","severity":"info","attributes":{"version":"1.0.0"}}]}'`}</pre>
            </Field>
            <div className="row">
              <button
                type="button"
                className="btn"
                onClick={() => void navigator.clipboard.writeText(created.ingestion_key)}
              >
                Copy key
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={() => navigate(`/services/${created.id}`)}
              >
                Open service
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function CreateServiceModal({
  workspaceId,
  onClose,
  onCreated,
  onError,
}: {
  workspaceId: string;
  onClose: () => void;
  onCreated: (service: ServiceCreated) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState<Environment>("production");
  const [description, setDescription] = useState("");
  const [ownerTeam, setOwnerTeam] = useState("");
  const [healthUrl, setHealthUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setLocalError(null);
    try {
      const payload: Record<string, unknown> = {
        name,
        environment,
        description,
        owner_team: ownerTeam,
      };
      if (healthUrl.trim()) payload.health_check = { url: healthUrl.trim() };
      const service = await api<ServiceCreated>(`/workspaces/${workspaceId}/services`, {
        method: "POST",
        body: payload,
      });
      onCreated(service);
    } catch (cause) {
      setLocalError(describeError(cause));
      onError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Register a service" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        {localError && <Notice tone="error">{localError}</Notice>}
        <Field label="Service name" hint="Unique within the chosen environment.">
          <input
            className="input"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="checkout-api"
          />
        </Field>
        <div className="form-grid">
          <Field label="Environment">
            <select
              className="select"
              value={environment}
              onChange={(event) => setEnvironment(event.target.value as Environment)}
            >
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="development">development</option>
            </select>
          </Field>
          <Field label="Owner team">
            <input
              className="input"
              value={ownerTeam}
              onChange={(event) => setOwnerTeam(event.target.value)}
              placeholder="platform"
            />
          </Field>
        </div>
        <Field label="Description">
          <textarea
            className="textarea"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What this service does and what failure means."
          />
        </Field>
        <Field
          label="Health check URL (optional)"
          hint="Public http(s) URL. Private, loopback and link-local targets are rejected unless an administrator explicitly enables them."
        >
          <input
            className="input mono"
            value={healthUrl}
            onChange={(event) => setHealthUrl(event.target.value)}
            placeholder="https://api.example.com/health"
          />
        </Field>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? <Spinner /> : null}
            Create service
          </button>
        </div>
      </form>
    </Modal>
  );
}
