import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { canWrite, useAuth } from "../auth/AuthContext";
import { Toasts } from "../components/Toasts";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingBlock,
  Modal,
  Notice,
  PageHeader,
  Spinner,
} from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useToasts } from "../hooks/useToasts";
import { api, apiDownload, describeError, downloadBlob } from "../lib/api";
import { bytes, formatRelative, formatTimestamp } from "../lib/format";
import type {
  AIAnalysis,
  EvidenceKind,
  IncidentDetail,
  IncidentStatus,
  Member,
  Report,
} from "../lib/types";

/**
 * Incident room (PRD OZ5 + OZ7).
 *
 * Owns the lifecycle controls, the timeline, evidence links, follow-up actions,
 * the evidence-grounded AI panel and report export. The server is the authority on
 * which transitions are legal: this screen only offers the ones it knows about and
 * shows the server's message verbatim when it disagrees.
 */

const LIFECYCLE: IncidentStatus[] = [
  "open",
  "acknowledged",
  "investigating",
  "mitigating",
  "monitoring",
  "resolved",
  "closed",
];

// Mirrors backend/app/models/incident.py INCIDENT_TRANSITIONS. Kept in sync by hand;
// the API rejects anything else and the error is surfaced to the user.
const TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["acknowledged", "investigating"],
  acknowledged: ["investigating", "open"],
  investigating: ["mitigating", "monitoring", "acknowledged"],
  mitigating: ["monitoring", "investigating"],
  monitoring: ["resolved", "mitigating", "investigating"],
  resolved: ["closed", "monitoring"],
  closed: [],
};

const RESOLUTION_STATES: IncidentStatus[] = ["resolved", "closed"];

const EVIDENCE_KINDS: EvidenceKind[] = [
  "log_event",
  "health_check_result",
  "webhook_event",
  "deployment",
  "external_url",
  "note",
];

const ID_KINDS: EvidenceKind[] = ["log_event", "health_check_result", "webhook_event", "deployment"];

function stateLabel(status: string): string {
  return status ? status.replace(/_/g, " ") : "—";
}

export default function IncidentDetailPage() {
  const { incidentId } = useParams<{ incidentId: string }>();
  const { workspace, role } = useAuth();
  const { toasts, notify } = useToasts();

  const workspaceId = workspace?.id ?? "";
  const writable = canWrite(role, "incidents");

  const incident = useAsync<IncidentDetail>(
    (signal) => api<IncidentDetail>(`/workspaces/${workspaceId}/incidents/${incidentId}`, { signal }),
    [workspaceId, incidentId],
  );
  const analyses = useAsync<AIAnalysis[]>(
    (signal) =>
      api<AIAnalysis[]>(`/workspaces/${workspaceId}/incidents/${incidentId}/ai-analyses`, { signal }),
    [workspaceId, incidentId],
  );
  const reports = useAsync<Report[]>(
    (signal) => api<Report[]>(`/workspaces/${workspaceId}/incidents/${incidentId}/reports`, { signal }),
    [workspaceId, incidentId],
  );
  const members = useAsync<Member[]>(
    (signal) => api<Member[]>(`/workspaces/${workspaceId}/members`, { signal }),
    [workspaceId],
  );

  const [pendingStatus, setPendingStatus] = useState<IncidentStatus | null>(null);
  const [transitionReason, setTransitionReason] = useState("");
  const [transitionBusy, setTransitionBusy] = useState(false);

  const data = incident.data;

  const changeStatus = async (status: IncidentStatus, note: string) => {
    setTransitionBusy(true);
    try {
      await api<IncidentDetail>(`/workspaces/${workspaceId}/incidents/${incidentId}`, {
        method: "PATCH",
        body: { status, ...(RESOLUTION_STATES.includes(status) ? { resolution_note: note } : {}) },
      });
      notify(`Incident moved to ${stateLabel(status)}`);
      incident.reload();
      setPendingStatus(null);
      setTransitionReason("");
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setTransitionBusy(false);
    }
  };

  const assignOwner = async (ownerId: string) => {
    try {
      await api<IncidentDetail>(`/workspaces/${workspaceId}/incidents/${incidentId}`, {
        method: "PATCH",
        body: { owner_id: ownerId || null },
      });
      notify(ownerId ? "Owner assigned" : "Owner unassigned");
      incident.reload();
    } catch (cause) {
      notify(describeError(cause), "error");
    }
  };

  if (incident.error) {
    return (
      <div className="page">
        <PageHeader title="Incident" subtitle="This incident could not be loaded." />
        <ErrorState error={incident.error} onRetry={incident.reload} />
        <p className="stat-hint">
          <Link to="/incidents">Back to the incident queue</Link>
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <PageHeader title="Incident" subtitle="Loading the incident room…" />
        <LoadingBlock lines={8} />
      </div>
    );
  }

  const closed = data.status === "closed";
  const allowed = TRANSITIONS[data.status] ?? [];

  return (
    <div className="page">
      <PageHeader
        title={data.title}
        subtitle={`${data.service_name ?? "workspace-wide"} · detected ${formatTimestamp(
          data.detected_at,
        )} · ${formatRelative(data.detected_at)}`}
        actions={
          <div className="btn-group">
            <Link className="btn ghost" to="/incidents">
              ← Queue
            </Link>
            <button type="button" className="btn" onClick={incident.reload}>
              Refresh
            </button>
          </div>
        }
      />

      <div className="row" style={{ gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        <Badge value={data.status} />
        <Badge value={data.severity} />
        {data.owner_label ? (
          <Badge value={`owner: ${data.owner_label}`} className="plain" />
        ) : (
          <Badge value="unassigned" className="plain" />
        )}
        {closed && <span className="stat-hint">A closed incident is immutable in the MVP.</span>}
      </div>

      <div className="split">
        <div className="stack">
          <Card title="Lifecycle">
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
              {LIFECYCLE.map((state) => (
                <Badge
                  key={state}
                  value={state}
                  className={state === data.status ? "" : "plain"}
                />
              ))}
            </div>
            <p className="stat-hint" style={{ margin: "0 0 12px" }}>
              The highlighted state is current. Only the transitions below are accepted by the API;
              moving to resolved or closed requires a resolution note of at least 10 characters.
            </p>

            {writable && !closed ? (
              <div className="actions-cell">
                {allowed.map((state) => (
                  <button
                    key={state}
                    type="button"
                    className={`btn small ${RESOLUTION_STATES.includes(state) ? "primary" : ""}`}
                    disabled={transitionBusy}
                    onClick={() => {
                      if (RESOLUTION_STATES.includes(state)) {
                        setPendingStatus(state);
                        setTransitionReason(data.resolution_note ?? "");
                      } else {
                        void changeStatus(state, "");
                      }
                    }}
                  >
                    Move to {stateLabel(state)}
                  </button>
                ))}
                {allowed.length === 0 && <span className="stat-hint">No transitions available.</span>}
              </div>
            ) : null}

            {!closed && (
              <div className="divider" />
            )}
            {!closed && (
              <div className="filter-bar">
                <Field label="Owner" hint="Ownership changes are recorded on the timeline and audited.">
                  <select
                    className="select"
                    value={data.owner_id ?? ""}
                    disabled={!writable}
                    onChange={(event) => void assignOwner(event.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {(members.data ?? []).map((member) => (
                      <option key={member.user_id} value={member.user_id}>
                        {member.full_name} ({member.role})
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            )}

            {data.resolution_note && (
              <>
                <div className="divider" />
                <div className="ai-section" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
                  <h4>Resolution note</h4>
                  <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{data.resolution_note}</p>
                </div>
              </>
            )}
          </Card>

          <TimelinePanel
            incident={data}
            workspaceId={workspaceId}
            writable={writable}
            onChanged={incident.reload}
            notify={notify}
          />

          <EvidencePanel
            incident={data}
            workspaceId={workspaceId}
            writable={writable}
            onChanged={incident.reload}
            notify={notify}
          />

          <FollowUpsPanel
            incident={data}
            workspaceId={workspaceId}
            writable={writable}
            onChanged={incident.reload}
            notify={notify}
          />
        </div>

        <div className="stack">
          <AiPanel
            workspaceId={workspaceId}
            incidentId={incidentId ?? ""}
            analyses={analyses}
            canRun={canWrite(role, "ai")}
            notify={notify}
            onChanged={() => {
              analyses.reload();
              incident.reload();
            }}
          />

          <ReportsPanel
            workspaceId={workspaceId}
            incidentId={incidentId ?? ""}
            reports={reports}
            notify={notify}
            onChanged={incident.reload}
          />
        </div>
      </div>

      {pendingStatus && (
        <Modal title={`Move to ${stateLabel(pendingStatus)}`} onClose={() => setPendingStatus(null)}>
          <div className="stack">
            <p className="stat-hint" style={{ margin: 0 }}>
              {pendingStatus === "closed"
                ? "Closing is final in the MVP: the incident becomes immutable. The note is stored as the resolution summary."
                : "Resolving records the fix that brought the incident down. The note is required and appears in exported reports."}
            </p>
            <Field label="Resolution note" hint="At least 10 characters. This is evidence, not a summary of feelings.">
              <textarea
                className="textarea"
                value={transitionReason}
                onChange={(event) => setTransitionReason(event.target.value)}
                placeholder="Raised the checkout DB pool ceiling to 60 and confirmed p95 back under 400ms for 30 minutes."
              />
            </Field>
            {transitionReason.trim().length < 10 && (
              <span className="hint" style={{ color: "var(--danger)" }}>
                {transitionReason.trim().length} / 10 characters.
              </span>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="btn"
                onClick={() => setPendingStatus(null)}
                disabled={transitionBusy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={transitionBusy || transitionReason.trim().length < 10}
                onClick={() => void changeStatus(pendingStatus, transitionReason)}
              >
                {transitionBusy ? <Spinner /> : null}
                Move to {stateLabel(pendingStatus)}
              </button>
            </div>
          </div>
        </Modal>
      )}

      <Toasts toasts={toasts} />
    </div>
  );
}

function TimelinePanel({
  incident,
  workspaceId,
  writable,
  onChanged,
  notify,
}: {
  incident: IncidentDetail;
  workspaceId: string;
  writable: boolean;
  onChanged: () => void;
  notify: (text: string, tone?: "info" | "error") => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!comment.trim()) return;
    setBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/incidents/${incident.id}/comments`, {
        method: "POST",
        body: { message: comment.trim() },
      });
      setComment("");
      notify("Comment added to the timeline");
      onChanged();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Timeline" action={<span className="stat-hint">{incident.events.length} entries</span>}>
      {incident.events.length === 0 ? (
        <EmptyState title="No timeline entries yet" />
      ) : (
        <ul className="timeline">
          {[...incident.events].reverse().map((event) => (
            <li key={event.id} className={event.event_type === "status_change" ? "highlight" : ""}>
              <div className="tl-meta">
                {formatTimestamp(event.created_at)} · {event.event_type.replace(/_/g, " ")}
                {event.from_status && event.to_status
                  ? ` · ${stateLabel(event.from_status)} → ${stateLabel(event.to_status)}`
                  : ""}
              </div>
              <div>
                <span className="tl-actor">{event.actor_label}</span>{" "}
                <span style={{ whiteSpace: "pre-wrap" }}>{event.message}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {writable && incident.status !== "closed" ? (
        <form onSubmit={submit} className="stack" style={{ marginTop: 12 }}>
          <Field label="Add a comment" hint="Recorded with your name, timestamped, and never edited in place.">
            <textarea
              className="textarea"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              maxLength={10000}
              placeholder="Bumped the DB pool; watching p95 for the next 30 minutes."
            />
          </Field>
          <div className="row">
            <button type="submit" className="btn primary" disabled={busy || !comment.trim()}>
              {busy ? <Spinner /> : null}
              Add comment
            </button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

function EvidencePanel({
  incident,
  workspaceId,
  writable,
  onChanged,
  notify,
}: {
  incident: IncidentDetail;
  workspaceId: string;
  writable: boolean;
  onChanged: () => void;
  notify: (text: string, tone?: "info" | "error") => void;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <Card
      title="Evidence"
      action={
        writable && incident.status !== "closed" ? (
          <button type="button" className="btn ghost small" onClick={() => setAdding(true)}>
            Add evidence
          </button>
        ) : (
          <span className="stat-hint">{incident.evidence.length} links</span>
        )
      }
    >
      <p className="stat-hint" style={{ marginTop: 0 }}>
        Evidence is append-only: each link points at a stored log event, health result, deployment or
        note. Links cannot be edited, so the investigation record stays intact.
      </p>
      {incident.evidence.length === 0 ? (
        <EmptyState title="No evidence linked yet">
          Link the log events, health results or deployments that made this incident visible.
        </EmptyState>
      ) : (
        <div>
          {incident.evidence.map((link) => (
            <div key={link.id} className="evidence-item">
              <div className="ev-head">
                <Badge value={link.kind.replace(/_/g, " ")} className="plain" />
                <strong>{link.title || link.kind}</strong>
                <span className="stat-hint">{formatTimestamp(link.created_at)}</span>
              </div>
              {link.excerpt && <div className="ev-excerpt">{link.excerpt}</div>}
              <div className="row" style={{ gap: 10, marginTop: 6, flexWrap: "wrap" }}>
                {link.kind === "log_event" && link.ref_id && (
                  <Link className="stat-hint" to={`/logs?range=7d&event=${link.ref_id}`}>
                    Open in log explorer
                  </Link>
                )}
                {link.url && (
                  <a className="stat-hint" href={link.url} target="_blank" rel="noreferrer noopener">
                    {link.url.length > 60 ? `${link.url.slice(0, 60)}…` : link.url}
                  </a>
                )}
                {link.ref_id && link.kind !== "log_event" && (
                  <span className="stat-hint mono">{link.ref_id}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {adding && (
        <EvidenceModal
          workspaceId={workspaceId}
          incidentId={incident.id}
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            notify("Evidence linked");
            onChanged();
          }}
          onError={(message) => notify(message, "error")}
        />
      )}
    </Card>
  );
}

function EvidenceModal({
  workspaceId,
  incidentId,
  onClose,
  onAdded,
  onError,
}: {
  workspaceId: string;
  incidentId: string;
  onClose: () => void;
  onAdded: () => void;
  onError: (message: string) => void;
}) {
  const [kind, setKind] = useState<EvidenceKind>("log_event");
  const [title, setTitle] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [url, setUrl] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    // Accept a bare id or a pasted log-explorer link, so evidence can be linked
    // straight from the URL the investigator was looking at.
    const urlMatch = /[?&]event=([0-9a-f-]{8,})/i.exec(reference);
    const refId = (urlMatch?.[1] ?? reference.trim()) || null;
    try {
      await api(`/workspaces/${workspaceId}/incidents/${incidentId}/evidence`, {
        method: "POST",
        body: {
          kind,
          ref_id: ID_KINDS.includes(kind) ? refId : null,
          url,
          title,
          excerpt,
          metadata: {},
        },
      });
      onAdded();
    } catch (cause) {
      onError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Link evidence" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <Field label="Kind">
          <select
            className="select"
            value={kind}
            onChange={(event) => setKind(event.target.value as EvidenceKind)}
          >
            {EVIDENCE_KINDS.map((option) => (
              <option key={option} value={option}>
                {option.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </Field>

        {ID_KINDS.includes(kind) ? (
          <Field
            label="Reference id"
            hint="Paste the id, or the /logs?event=… link you were looking at. The API rejects an id that is not in this workspace."
          >
            <input
              className="input mono"
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="f7cb22a4-6587-46d4-a468-4cd13f616813"
            />
          </Field>
        ) : null}

        {kind === "external_url" ? (
          <Field label="URL" hint="Shown as-is, opened in a new tab with rel=noopener.">
            <input
              className="input mono"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/acme/storefront/commit/abc123"
            />
          </Field>
        ) : null}

        <Field label="Title">
          <input
            className="input"
            value={title}
            maxLength={240}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="authorizer timeout"
          />
        </Field>

        <Field
          label="Excerpt"
          hint="Paste only what a reviewer needs. Secrets are redacted before anything is sent to a model, but keep it minimal anyway."
        >
          <textarea
            className="textarea"
            value={excerpt}
            maxLength={10000}
            onChange={(event) => setExcerpt(event.target.value)}
          />
        </Field>

        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? <Spinner /> : null}
            Link evidence
          </button>
        </div>
      </form>
    </Modal>
  );
}

function FollowUpsPanel({
  incident,
  workspaceId,
  writable,
  onChanged,
  notify,
}: {
  incident: IncidentDetail;
  workspaceId: string;
  writable: boolean;
  onChanged: () => void;
  notify: (text: string, tone?: "info" | "error") => void;
}) {
  const [text, setText] = useState("");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);

  const items = incident.follow_up_actions ?? [];

  const save = async (next: Array<{ text: string; owner?: string; done?: boolean }>) => {
    setBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/incidents/${incident.id}`, {
        method: "PATCH",
        body: { follow_up_actions: next },
      });
      onChanged();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setBusy(false);
    }
  };

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    await save([...items, { text: text.trim(), owner: owner.trim(), done: false }]);
    setText("");
    setOwner("");
    notify("Follow-up action added");
  };

  return (
    <Card
      title="Follow-up actions"
      action={<span className="stat-hint">{items.filter((item) => !item.done).length} open</span>}
    >
      <p className="stat-hint" style={{ marginTop: 0 }}>
        Work that outlives the incident. Carried into the exported report so the next incident starts
        from a better place.
      </p>
      {items.length === 0 ? (
        <EmptyState title="No follow-up actions yet" />
      ) : (
        <div className="stack">
          {items.map((item, index) => (
            <label key={`${item.text}-${index}`} className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(item.done)}
                disabled={!writable || busy}
                onChange={() =>
                  void save(
                    items.map((candidate, position) =>
                      position === index ? { ...candidate, done: !candidate.done } : candidate,
                    ),
                  )
                }
              />
              <span style={{ textDecoration: item.done ? "line-through" : "none" }}>{item.text}</span>
              {item.owner ? <span className="stat-hint">· {item.owner}</span> : null}
            </label>
          ))}
        </div>
      )}

      {writable && incident.status !== "closed" ? (
        <form onSubmit={add} className="filter-bar" style={{ marginTop: 12 }}>
          <Field label="New action" full>
            <input
              className="input"
              value={text}
              maxLength={500}
              onChange={(event) => setText(event.target.value)}
              placeholder="Raise the DB pool ceiling and alert on saturation"
            />
          </Field>
          <Field label="Owner team">
            <input
              className="input"
              value={owner}
              maxLength={200}
              onChange={(event) => setOwner(event.target.value)}
              placeholder="Platform"
            />
          </Field>
          <button type="submit" className="btn primary" disabled={busy || !text.trim()}>
            {busy ? <Spinner /> : null}
            Add
          </button>
        </form>
      ) : null}
    </Card>
  );
}

function AiPanel({
  workspaceId,
  incidentId,
  analyses,
  canRun,
  notify,
  onChanged,
}: {
  workspaceId: string;
  incidentId: string;
  analyses: { data: AIAnalysis[] | null; loading: boolean; error: Error | null; reload: () => void };
  canRun: boolean;
  notify: (text: string, tone?: "info" | "error") => void;
  onChanged: () => void;
}) {
  const [running, setRunning] = useState(false);
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);

  const latest = useMemo(() => analyses.data?.[0] ?? null, [analyses.data]);

  const run = async () => {
    setRunning(true);
    try {
      await api(`/workspaces/${workspaceId}/incidents/${incidentId}/ai-analysis`, { method: "POST" });
      notify("Analysis complete — facts are cited, hypotheses are unvalidated");
      onChanged();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setRunning(false);
    }
  };

  const sendFeedback = async (value: "accepted" | "edited" | "rejected") => {
    if (!latest) return;
    setFeedbackBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/ai-analyses/${latest.id}/feedback`, {
        method: "POST",
        body: { feedback: value, note: feedbackNote },
      });
      notify(`Feedback recorded: ${value}`);
      setFeedbackNote("");
      onChanged();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setFeedbackBusy(false);
    }
  };

  const output = latest?.output;

  return (
    <Card
      title="AI investigation"
      action={
        <button type="button" className="btn ghost small" onClick={() => void run()} disabled={!canRun || running}>
          {running ? <Spinner /> : null}
          {latest ? "Run again" : "Run analysis"}
        </button>
      }
    >
      <Notice tone="info">
        Advisory and read-only. Observed facts must cite stored evidence; uncited facts are dropped by
        the server, hypotheses are labelled unvalidated, and nothing here can change infrastructure.
      </Notice>

      {!canRun && (
        <p className="stat-hint">
          Your role can read analyses but not request new ones. Runs require the AI permission.
        </p>
      )}

      {analyses.error && <ErrorState error={analyses.error} onRetry={analyses.reload} />}

      {analyses.loading && !analyses.data && <LoadingBlock lines={4} />}

      {!analyses.loading && !latest && !analyses.error && (
        <EmptyState title="No analysis yet">
          Run an analysis to get observed facts with citations, inferred hypotheses, missing information
          and recommended next checks — all from evidence already stored on this incident.
        </EmptyState>
      )}

      {latest && (
        <div style={{ marginTop: 12 }}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            <Badge value={latest.status} />
            <Badge value={latest.provider} className="plain" />
            <Badge value={latest.model_id} className="plain" />
            <span className="stat-hint">
              {latest.citation_count} citations · {formatTimestamp(latest.created_at)}
              {latest.latency_ms ? ` · ${Math.round(latest.latency_ms)}ms` : ""}
            </span>
          </div>

          {latest.error && <Notice tone="error">{latest.error}</Notice>}
          {latest.invalid_citations.length > 0 && (
            <Notice tone="warn">
              {latest.invalid_citations.length} citation
              {latest.invalid_citations.length === 1 ? "" : "s"} could not be resolved to stored
              evidence and were dropped: {latest.invalid_citations.join(", ")}
            </Notice>
          )}

          {output && (
            <>
              <div className="ai-section">
                <h4>Observed facts</h4>
                {output.observed_facts.length === 0 ? (
                  <p className="stat-hint" style={{ margin: 0 }}>
                    No fact survived citation checking — the evidence pack was too thin.
                  </p>
                ) : (
                  <ul className="ai-list">
                    {output.observed_facts.map((fact, index) => (
                      <li key={`${fact.text}-${index}`}>
                        {fact.text}
                        <div className="citations">
                          {fact.citations.map((citation) => {
                            const source = output.sources?.[citation];
                            const href =
                              source && source.ref_id && ["log", "log_event"].includes(source.kind)
                                ? `/logs?range=7d&event=${source.ref_id}`
                                : null;
                            return href ? (
                              <Link key={citation} className="citation" to={href} title={source?.label ?? citation}>
                                {citation}
                              </Link>
                            ) : (
                              <span key={citation} className="citation" title={source?.label ?? "stored evidence"}>
                                {citation}
                              </span>
                            );
                          })}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="ai-section">
                <h4>Inferred hypotheses</h4>
                {output.hypotheses.length === 0 ? (
                  <p className="stat-hint" style={{ margin: 0 }}>
                    No hypothesis was proposed. That is a valid outcome when evidence is inconclusive.
                  </p>
                ) : (
                  <ul className="ai-list">
                    {output.hypotheses.map((hypothesis, index) => (
                      <li key={`${hypothesis.text}-${index}`}>
                        {hypothesis.text}
                        <span className="confidence">confidence: {hypothesis.confidence} (unvalidated)</span>
                        {hypothesis.reasoning && (
                          <div className="stat-hint" style={{ marginTop: 4 }}>
                            Why: {hypothesis.reasoning}
                          </div>
                        )}
                        {hypothesis.citations.length > 0 && (
                          <div className="citations">
                            {hypothesis.citations.map((citation) => (
                              <span key={citation} className="citation" title="supporting evidence">
                                {citation}
                              </span>
                            ))}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="ai-section">
                <h4>Missing information</h4>
                {output.missing_information.length === 0 ? (
                  <p className="stat-hint" style={{ margin: 0 }}>
                    Nothing was flagged as missing.
                  </p>
                ) : (
                  <ul className="plain-list">
                    {output.missing_information.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="ai-section">
                <h4>Recommended next checks</h4>
                {output.recommended_next_checks.length === 0 ? (
                  <p className="stat-hint" style={{ margin: 0 }}>
                    No next checks were proposed.
                  </p>
                ) : (
                  <ul className="ai-list">
                    {output.recommended_next_checks.map((check, index) => (
                      <li key={`${check.text}-${index}`}>
                        {check.text}
                        {check.rationale && (
                          <div className="stat-hint" style={{ marginTop: 4 }}>
                            {check.rationale}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {output.meta?.disclaimer && (
                <p className="stat-hint" style={{ marginTop: 12 }}>
                  {output.meta.disclaimer}
                </p>
              )}
            </>
          )}

          <div className="divider" />

          <div className="ai-section" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
            <h4>Was this useful?</h4>
            <div className="row" style={{ gap: 6, marginBottom: 8 }}>
              {(["accepted", "edited", "rejected"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`btn small ${latest.feedback === value ? "primary" : ""}`}
                  disabled={!canRun || feedbackBusy}
                  onClick={() => void sendFeedback(value)}
                >
                  {value}
                </button>
              ))}
              {latest.feedback && <Badge value={latest.feedback} className="plain" />}
            </div>
            <input
              className="input"
              value={feedbackNote}
              maxLength={2000}
              disabled={!canRun}
              onChange={(event) => setFeedbackNote(event.target.value)}
              placeholder="Optional note stored with the feedback (goes into the AI eval set)"
            />
          </div>

          {(analyses.data?.length ?? 0) > 1 && (
            <p className="stat-hint" style={{ marginTop: 10 }}>
              {analyses.data!.length} analyses stored for this incident; showing the latest.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function ReportsPanel({
  workspaceId,
  incidentId,
  reports,
  notify,
  onChanged,
}: {
  workspaceId: string;
  incidentId: string;
  reports: { data: Report[] | null; loading: boolean; error: Error | null; reload: () => void };
  notify: (text: string, tone?: "info" | "error") => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const exportReport = async (format: "md" | "pdf") => {
    setBusy(format);
    try {
      const { blob, filename } = await apiDownload(
        `/workspaces/${workspaceId}/incidents/${incidentId}/reports?format=${format}`,
        "POST",
      );
      downloadBlob(blob, filename);
      notify(`${format.toUpperCase()} report exported`);
      reports.reload();
      onChanged();
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setBusy(null);
    }
  };

  const download = async (report: Report) => {
    setBusy(report.id);
    try {
      const { blob, filename } = await apiDownload(
        `/workspaces/${workspaceId}/reports/${report.id}/download`,
      );
      downloadBlob(blob, filename);
    } catch (cause) {
      notify(describeError(cause), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card title="Reports">
      <p className="stat-hint" style={{ marginTop: 0 }}>
        Generated from stored evidence only. The redaction level is recorded per report, so a
        viewer-safe export can be shared without exposing raw telemetry.
      </p>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        <button
          type="button"
          className="btn"
          onClick={() => void exportReport("md")}
          disabled={busy !== null}
        >
          {busy === "md" ? <Spinner /> : null}
          Export Markdown
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => void exportReport("pdf")}
          disabled={busy !== null}
        >
          {busy === "pdf" ? <Spinner /> : null}
          Export PDF
        </button>
      </div>

      {reports.error && <ErrorState error={reports.error} onRetry={reports.reload} />}
      {reports.loading && !reports.data && <LoadingBlock lines={2} />}
      {reports.data && reports.data.length === 0 && !reports.error && (
        <p className="stat-hint" style={{ margin: 0 }}>
          No reports generated yet.
        </p>
      )}
      {(reports.data ?? []).map((report) => (
        <div key={report.id} className="evidence-item">
          <div className="ev-head">
            <Badge value={report.format} className="plain" />
            <strong className="mono" style={{ fontSize: 12 }}>
              {report.filename}
            </strong>
          </div>
          <div className="stat-hint">
            {formatTimestamp(report.generated_at)} · {bytes(report.size_bytes)} · redaction:{" "}
            {report.redaction_level}
          </div>
          <button
            type="button"
            className="btn ghost small"
            style={{ marginTop: 6 }}
            onClick={() => void download(report)}
            disabled={busy !== null}
          >
            {busy === report.id ? <Spinner /> : null}
            Download
          </button>
        </div>
      ))}
    </Card>
  );
}
