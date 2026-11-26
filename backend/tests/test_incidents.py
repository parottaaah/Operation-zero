"""Incident lifecycle, timeline, evidence, reports and audit consistency."""

from __future__ import annotations

import pytest


def _incident(client, tenant, **overrides):
    payload = {"title": "Checkout latency spike", "summary": "p95 above target", **overrides}
    response = client.post(tenant.url("/incidents"), headers=tenant.headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _patch(client, tenant, incident_id, **payload):
    return client.patch(f"{tenant.url('/incidents')}/{incident_id}", headers=tenant.headers, json=payload)


def test_incident_creation_records_timeline(client, owner):
    incident = _incident(client, owner)
    assert incident["status"] == "open"
    assert incident["severity"] == "warning"
    assert incident["events"][0]["event_type"] == "created"
    assert incident["events"][0]["actor_label"]

    audit = client.get(owner.url("/audit-events?action=incident.create"), headers=owner.headers)
    assert audit.status_code == 200
    assert audit.json()["items"]


def test_full_lifecycle_with_required_resolution_note(client, owner):
    incident = _incident(client, owner)
    incident_id = incident["id"]

    assert _patch(client, owner, incident_id, status="acknowledged").status_code == 200
    assert _patch(client, owner, incident_id, status="investigating").status_code == 200
    assert _patch(client, owner, incident_id, status="mitigating").status_code == 200
    assert _patch(client, owner, incident_id, status="monitoring").status_code == 200

    missing_note = _patch(client, owner, incident_id, status="resolved")
    assert missing_note.status_code == 422
    assert "resolution note" in missing_note.json()["error"]["message"]

    resolved = _patch(
        client,
        owner,
        incident_id,
        status="resolved",
        resolution_note="Rolled back release 2026.11.3; error rate returned to baseline.",
        follow_up_actions=[{"text": "Add latency SLO alert", "owner": "platform", "done": False}],
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None
    assert body["follow_up_actions"][0]["text"] == "Add latency SLO alert"
    assert any(event["to_status"] == "resolved" for event in body["events"])

    closed = _patch(client, owner, incident_id, status="closed")
    assert closed.status_code == 200
    assert closed.json()["closed_at"] is not None

    immutable = _patch(client, owner, incident_id, title="Changed after close")
    assert immutable.status_code == 409


def test_invalid_transition_is_rejected(client, owner):
    incident = _incident(client, owner)
    response = _patch(
        client,
        owner,
        incident["id"],
        status="resolved",
        resolution_note="Skipping straight to resolved is not allowed.",
    )
    assert response.status_code == 409
    assert "invalid incident transition" in response.json()["error"]["message"]


def test_owner_assignment_must_be_member(client, owner, make_tenant):
    stranger = make_tenant()
    incident = _incident(client, owner)
    response = _patch(client, owner, incident["id"], owner_id=stranger.user_id)
    assert response.status_code == 422

    engineer = make_tenant(owner=owner, role="engineer")
    assigned = _patch(client, owner, incident["id"], owner_id=engineer.user_id)
    assert assigned.status_code == 200
    assert assigned.json()["owner_id"] == engineer.user_id
    assert assigned.json()["owner_label"]


def test_comments_are_timeline_events(client, owner):
    incident = _incident(client, owner)
    response = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/comments",
        headers=owner.headers,
        json={"message": "Checked dashboards; error budget burn is real."},
    )
    assert response.status_code == 201
    assert response.json()["event_type"] == "comment"

    detail = client.get(f"{owner.url('/incidents')}/{incident['id']}", headers=owner.headers).json()
    assert any(e["event_type"] == "comment" for e in detail["events"])


def test_evidence_links_are_tenant_scoped(client, owner, make_tenant, create_service):
    other = make_tenant(workspace_name="Other")
    other_service = client.post(
        other.url("/services"), headers=other.headers, json={"name": "other-svc"}
    ).json()
    other_log = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": other_service["ingestion_key"]},
        json={"events": [{"message": "other tenant log", "severity": "error"}]},
    ).json()["event_ids"][0]

    incident = _incident(client, owner)
    cross_tenant = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/evidence",
        headers=owner.headers,
        json={"kind": "log_event", "ref_id": other_log},
    )
    assert cross_tenant.status_code == 404

    service = create_service(owner)
    own_log = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": service["ingestion_key"]},
        json={"events": [{"message": "timeout on upstream", "severity": "error"}]},
    ).json()["event_ids"][0]
    linked = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/evidence",
        headers=owner.headers,
        json={"kind": "log_event", "ref_id": own_log, "title": "First timeout"},
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["kind"] == "log_event"

    detail = client.get(f"{owner.url('/incidents')}/{incident['id']}", headers=owner.headers).json()
    assert len(detail["evidence"]) == 1
    assert any(e["event_type"] == "evidence_linked" for e in detail["events"])


def test_evidence_excerpt_is_redacted(client, owner):
    incident = _incident(client, owner)
    response = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/evidence",
        headers=owner.headers,
        json={
            "kind": "note",
            "title": "Chat excerpt",
            "excerpt": "token=supersecret123 and bob@example.com",
        },
    )
    assert response.status_code == 201
    assert "supersecret123" not in response.json()["excerpt"]
    assert "bob@example.com" not in response.json()["excerpt"]


def test_report_export_markdown_pdf_and_viewer_redaction(client, owner, make_tenant):
    viewer = make_tenant(owner=owner, role="viewer")
    incident = _incident(client, owner)
    client.post(
        f"{owner.url('/incidents')}/{incident['id']}/evidence",
        headers=owner.headers,
        json={"kind": "note", "title": "Runbook", "excerpt": "RAW-DETAIL-XYZ"},
    )

    markdown = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/reports?format=md", headers=owner.headers
    )
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "Checkout latency spike" in markdown.text
    assert "RAW-DETAIL-XYZ" in markdown.text

    pdf = client.post(f"{owner.url('/incidents')}/{incident['id']}/reports?format=pdf", headers=owner.headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    viewer_md = client.post(
        f"{viewer.url('/incidents')}/{incident['id']}/reports?format=md", headers=viewer.headers
    )
    assert viewer_md.status_code == 200
    assert "RAW-DETAIL-XYZ" not in viewer_md.text
    assert "Viewer-redacted" in viewer_md.text

    listed = client.get(f"{owner.url('/incidents')}/{incident['id']}/reports", headers=owner.headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 3
    report_id = listed.json()[0]["id"]
    downloaded = client.get(f"{owner.url('/reports')}/{report_id}/download", headers=owner.headers)
    assert downloaded.status_code == 200
    assert downloaded.content

    export_audit = client.get(owner.url("/audit-events?action=report.export"), headers=owner.headers)
    assert export_audit.json()["items"]


def test_invalid_report_format_is_rejected(client, owner):
    incident = _incident(client, owner)
    response = client.post(
        f"{owner.url('/incidents')}/{incident['id']}/reports?format=docx", headers=owner.headers
    )
    assert response.status_code == 422


def test_incident_list_filters_and_cursor(client, owner):
    for index in range(3):
        _incident(client, owner, title=f"Incident {index}")
    response = client.get(owner.url("/incidents?limit=2"), headers=owner.headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"]

    second = client.get(owner.url(f"/incidents?limit=2&cursor={body['next_cursor']}"), headers=owner.headers)
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1

    open_only = client.get(owner.url("/incidents?status=open"), headers=owner.headers)
    assert len(open_only.json()["items"]) == 3
    closed_only = client.get(owner.url("/incidents?status=closed"), headers=owner.headers)
    assert closed_only.json()["items"] == []


def test_viewer_can_read_incidents(client, owner, make_tenant):
    viewer = make_tenant(owner=owner, role="viewer")
    incident = _incident(client, owner)
    assert client.get(viewer.url("/incidents"), headers=viewer.headers).status_code == 200
    assert (
        client.get(f"{viewer.url('/incidents')}/{incident['id']}", headers=viewer.headers).status_code == 200
    )
    denied = client.post(viewer.url("/incidents"), headers=viewer.headers, json={"title": "Viewer incident"})
    assert denied.status_code == 403


def test_incident_in_other_workspace_is_hidden(client, owner, make_tenant):
    other = make_tenant(workspace_name="Hidden")
    incident = _incident(client, owner)
    response = client.get(f"{other.url('/incidents')}/{incident['id']}", headers=other.headers)
    assert response.status_code == 404


@pytest.mark.parametrize("status_value", ["acknowledged", "investigating"])
def test_open_incident_can_move_to_triage_states(client, owner, status_value):
    incident = _incident(client, owner)
    response = _patch(client, owner, incident["id"], status=status_value)
    assert response.status_code == 200
    assert response.json()["status"] == status_value
