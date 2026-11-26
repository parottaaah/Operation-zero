"""AI investigation orchestrator: evidence → adapter → validated, cited output."""

from __future__ import annotations

import logging
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai import AIAnalysis, AIAnalysisStatus
from app.models.base import utcnow
from app.models.identity import User
from app.models.incident import Incident, IncidentEventType
from app.services.ai.adapters import get_adapter
from app.services.ai.evidence import build_evidence_pack, sources_index
from app.services.ai.prompts import build_prompt, detect_injection_markers
from app.services.audit import record_audit
from app.services.incidents import add_timeline

logger = logging.getLogger(__name__)


class Fact(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    citations: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    reasoning: str = Field(default="", max_length=1500)
    confidence: Literal["low", "medium", "high"] = "low"
    citations: list[str] = Field(default_factory=list)


class NextCheck(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    rationale: str = Field(default="", max_length=600)


class AnalysisOutput(BaseModel):
    observed_facts: list[Fact] = Field(default_factory=list, max_length=12)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    recommended_next_checks: list[NextCheck] = Field(default_factory=list, max_length=8)


def normalize_output(raw: dict, valid_ids: set[str]) -> tuple[dict, list[str], int]:
    """Validate the four-part structure and enforce citation integrity."""
    try:
        parsed = AnalysisOutput.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("AI output did not match the required schema") from exc

    invalid: list[str] = []
    citation_count = 0

    def clean(citations: list[str]) -> list[str]:
        nonlocal citation_count
        kept: list[str] = []
        for citation in citations:
            if citation in valid_ids:
                if citation not in kept:
                    kept.append(citation)
            elif citation not in invalid:
                invalid.append(citation)
        citation_count += len(kept)
        return kept

    facts = []
    dropped_facts = 0
    for fact in parsed.observed_facts:
        citations = clean(fact.citations)
        if not citations:
            dropped_facts += 1
            continue
        facts.append({"text": fact.text, "citations": citations})

    hypotheses = [
        {
            "text": hypothesis.text,
            "reasoning": hypothesis.reasoning,
            "confidence": hypothesis.confidence,
            "citations": clean(hypothesis.citations),
        }
        for hypothesis in parsed.hypotheses
    ]

    missing = [item[:600] for item in parsed.missing_information if item.strip()]
    if dropped_facts:
        missing.append(
            f"{dropped_facts} generated fact(s) were removed because they had no valid evidence citation."
        )
    if invalid:
        missing.append(
            f"{len(invalid)} cited reference(s) did not exist in the evidence pack and were discarded."
        )

    output = {
        "observed_facts": facts,
        "hypotheses": hypotheses,
        "missing_information": missing[:10],
        "recommended_next_checks": [
            {"text": check.text, "rationale": check.rationale} for check in parsed.recommended_next_checks
        ],
    }
    return output, invalid, citation_count


async def run_analysis(
    session: Session,
    *,
    incident: Incident,
    actor: User,
    request_id: str = "",
) -> AIAnalysis:
    evidence, context = build_evidence_pack(session, incident)
    payload = build_prompt(context, evidence)
    sources = sources_index(evidence)
    valid_ids = set(sources)

    marker_hits = sum(detect_injection_markers(item.summary) for item in evidence)
    adapter = get_adapter()
    started = time.perf_counter()
    analysis = AIAnalysis(
        workspace_id=incident.workspace_id,
        incident_id=incident.id,
        requested_by_id=actor.id,
        status=AIAnalysisStatus.FAILED,
        provider=adapter.name,
        model_id="",
        prompt_version=settings.ai_prompt_version,
        evidence_ids=list(valid_ids),
        output={},
        created_at=utcnow(),
    )

    try:
        result = await adapter.analyze(payload)
        output, invalid, citation_count = normalize_output(result.output, valid_ids)
        if not output["observed_facts"]:
            output["observed_facts"] = []
        if marker_hits:
            output["missing_information"].append(
                "Evidence contained text resembling embedded instructions; it was treated as "
                "untrusted data and not followed."
            )
        output["sources"] = sources
        output["meta"] = {
            "provider": result.provider,
            "model_id": result.model_id,
            "prompt_version": settings.ai_prompt_version,
            "evidence_count": len(evidence),
            "instruction_markers_in_evidence": marker_hits,
            "disclaimer": (
                "Observed facts cite stored evidence. Hypotheses are unvalidated and must be "
                "checked by a human before any action."
            ),
        }
        analysis.status = AIAnalysisStatus.COMPLETED
        analysis.provider = result.provider
        analysis.model_id = result.model_id
        analysis.output = output
        analysis.citation_count = citation_count
        analysis.invalid_citations = invalid
        analysis.latency_ms = round((time.perf_counter() - started) * 1000, 2)

        add_timeline(
            session,
            incident,
            event_type=IncidentEventType.AI_ANALYSIS,
            actor=actor,
            message=(
                f"AI analysis completed with {len(output['observed_facts'])} cited fact(s) and "
                f"{len(output['hypotheses'])} hypothesis(es) using provider '{result.provider}'."
            ),
            metadata={"analysis_id": str(analysis.id)},
        )
    except Exception as exc:
        logger.warning("AI analysis failed: %s", type(exc).__name__)
        analysis.status = AIAnalysisStatus.FAILED
        analysis.error = f"{type(exc).__name__}: {str(exc)[:400]}"
        analysis.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        analysis.output = {
            "observed_facts": [],
            "hypotheses": [],
            "missing_information": [
                "The AI provider was unavailable. Monitoring, logs, alerts and the incident "
                "workflow continue to work without AI."
            ],
            "recommended_next_checks": [],
            "sources": sources,
            "meta": {"provider": adapter.name, "prompt_version": settings.ai_prompt_version},
        }

    session.add(analysis)
    session.flush()
    record_audit(
        session,
        action="ai.analysis_request",
        workspace_id=incident.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="ai_analysis",
        target_id=analysis.id,
        request_id=request_id,
        metadata={
            "incident_id": str(incident.id),
            "provider": analysis.provider,
            "model_id": analysis.model_id,
            "prompt_version": analysis.prompt_version,
            "status": analysis.status.value,
            "evidence_count": len(evidence),
        },
    )
    return analysis


def record_feedback(
    session: Session,
    analysis: AIAnalysis,
    *,
    actor: User,
    feedback: str,
    note: str = "",
    request_id: str = "",
) -> AIAnalysis:
    from app.core.errors import ValidationFailed
    from app.models.ai import AIFeedback

    try:
        value = AIFeedback(feedback)
    except ValueError as exc:
        raise ValidationFailed("feedback must be accepted, edited or rejected") from exc
    analysis.feedback = value
    analysis.feedback_note = note[:2000]
    analysis.feedback_by_id = actor.id
    analysis.feedback_at = utcnow()
    record_audit(
        session,
        action="ai.feedback",
        workspace_id=analysis.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="ai_analysis",
        target_id=analysis.id,
        request_id=request_id,
        metadata={"feedback": value.value},
    )
    return analysis


__all__ = ["run_analysis", "normalize_output", "record_feedback", "AnalysisOutput"]
