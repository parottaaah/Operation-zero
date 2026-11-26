import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { formatNumber, formatRelative, formatTimestamp } from "../lib/format";
import type { Overview } from "../lib/types";
import { Badge, Card, EmptyState, ErrorState, LoadingBlock, PageHeader, Stat } from "../components/ui";

export default function OverviewPage() {
  const { workspace, role } = useAuth();
  const navigate = useNavigate();
  const overview = useAsync<Overview>(
    (signal) => api<Overview>(`/workspaces/${workspace?.id}/overview`, { signal }),
    [workspace?.id],
  );

  useEffect(() => {
    const timer = window.setInterval(overview.reload, 30_000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id]);

  if (!workspace) return null;
  if (overview.error) return <ErrorState error={overview.error} onRetry={overview.reload} />;
  if (overview.loading && !overview.data) {
    return (
      <div className="page">
        <PageHeader title="Overview" subtitle="Control-room snapshot of operational health." />
        <LoadingBlock lines={8} />
      </div>
    );
  }
  const data = overview.data!;
  const totalServices = Object.values(data.services).reduce((sum, value) => sum + value, 0);
  const healthy = data.services.healthy ?? 0;
  const degraded = data.services.degraded ?? 0;
  const down = data.services.down ?? 0;

  return (
    <div className="page">
      <PageHeader
        title="Overview"
        subtitle={`${data.workspace.name} · ${data.workspace.timezone}. Signals are shown as stored; nothing here is inferred.`}
        actions={
          <button type="button" className="btn" onClick={overview.reload}>
            Refresh
          </button>
        }
      />

      <div className="grid cols-4">
        <Stat
          label="Active incidents"
          value={data.active_incidents.length}
          hint={
            data.active_incidents.length > 0 ? (
              <Link to="/incidents">Open incident queue</Link>
            ) : (
              "No open incidents"
            )
          }
        />
        <Stat
          label="Service health"
          value={`${healthy}/${totalServices}`}
          hint={`${degraded} degraded · ${down} down`}
        />
        <Stat
          label="Log events · 24h"
          value={formatNumber(data.ingestion.events_24h)}
          hint={`Last received ${formatRelative(data.ingestion.last_received_at)}`}
        />
        <Stat
          label="AI analyses"
          value={data.ai.completed}
          hint={`${data.ai.failed} failed · provider ${data.ai.provider}`}
        />
      </div>

      {totalServices === 0 && (
        <Card>
          <EmptyState
            title="Start with one service"
            action={
              <button type="button" className="btn primary" onClick={() => navigate("/services")}>
                Register a service
              </button>
            }
          >
            Register a service, attach an HTTP health check and copy its ingestion key. OPERATION
            ZERO shows the first health result within one interval, then logs, alerts and incidents
            become useful.
          </EmptyState>
        </Card>
      )}

      <div className="grid cols-2">
        <Card
          title="Active incidents"
          action={
            <Link className="btn ghost small" to="/incidents">
              All incidents
            </Link>
          }
        >
          {data.active_incidents.length === 0 ? (
            <p style={{ color: "var(--muted)", margin: 0 }}>
              No open incidents. Alerts can be converted into incidents from the alerts view.
            </p>
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {data.active_incidents.map((incident) => (
                <Link
                  key={incident.id}
                  to={`/incidents/${incident.id}`}
                  className="row"
                  style={{ justifyContent: "space-between", color: "var(--text)" }}
                >
                  <span>{incident.title}</span>
                  <span className="row" style={{ gap: 8 }}>
                    <Badge value={incident.severity} />
                    <Badge value={incident.status} />
                    <span className="stat-hint">{formatRelative(incident.detected_at)}</span>
                  </span>
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card
          title="Recent alerts"
          action={
            <Link className="btn ghost small" to="/alerts">
              Alert queue
            </Link>
          }
        >
          {data.recent_alerts.length === 0 ? (
            <p style={{ color: "var(--muted)", margin: 0 }}>No alerts have fired yet.</p>
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {data.recent_alerts.map((alert) => (
                <div key={alert.id} className="row" style={{ justifyContent: "space-between" }}>
                  <span>
                    {alert.title}
                    {alert.occurrence_count > 1 && (
                      <span className="stat-hint"> ×{alert.occurrence_count}</span>
                    )}
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Badge value={alert.severity} />
                    <Badge value={alert.status} />
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card
          title="Deployment context"
          action={
            <Link className="btn ghost small" to="/deployments">
              View deployments
            </Link>
          }
        >
          {data.recent_deployments.length === 0 ? (
            <p style={{ color: "var(--muted)", margin: 0 }}>
              No verified repository events yet. Connect GitHub with least-privilege scopes in{" "}
              <Link to="/integrations">Integrations</Link>. Commits are shown as temporal context,
              never as proof of cause.
            </p>
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {data.recent_deployments.map((event) => (
                <div key={event.id} className="row" style={{ justifyContent: "space-between" }}>
                  <span className="mono" style={{ fontSize: 12 }}>
                    {event.repository} · {event.event_type} {event.action}
                  </span>
                  <span className="stat-hint">{formatRelative(event.occurred_at)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Ingestion & data policy">
          <dl className="kv">
            <dt>Last event</dt>
            <dd>{formatTimestamp(data.ingestion.last_received_at)}</dd>
            <dt>Ingestion health</dt>
            <dd>{data.ingestion.healthy ? "receiving" : "idle or not configured"}</dd>
            <dt>Role</dt>
            <dd>{role ?? "—"}</dd>
            <dt>AI feedback</dt>
            <dd>
              {Object.entries(data.ai.feedback)
                .map(([key, value]) => `${key} ${value}`)
                .join(" · ") || "no ratings yet"}
            </dd>
          </dl>
          <div className="divider" />
          <p className="stat-hint" style={{ margin: 0 }}>
            Secrets are redacted before persistence and before any external AI call. Retention is
            configurable per workspace in <Link to="/settings">Settings</Link>.
          </p>
        </Card>
      </div>
    </div>
  );
}
