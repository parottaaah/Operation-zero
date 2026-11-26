"""AI provider adapters.

* ``LocalDeterministicAdapter`` — no network, no provider, always available. It
  builds a real evidence-grounded summary from the same structured evidence the
  hosted model would receive, so offline/dev/pilot-without-AI still works.
* ``OpenAICompatibleAdapter`` — any OpenAI-compatible chat-completions endpoint.
  The provider is a configuration detail; the orchestrator never depends on it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings
from app.services.ai.prompts import EvidenceItem, PromptPayload


@dataclass
class AdapterResult:
    output: dict
    provider: str
    model_id: str


class AIAdapter(Protocol):
    name: str

    async def analyze(self, payload: PromptPayload) -> AdapterResult: ...


def _units(value: float) -> str:
    return f"{value * 100:.1f}%"


class LocalDeterministicAdapter:
    """Builds a four-part report using only measured evidence."""

    name = "local-deterministic"

    async def analyze(self, payload: PromptPayload) -> AdapterResult:
        evidence = payload.evidence
        by_kind: dict[str, list[EvidenceItem]] = {}
        for item in evidence:
            by_kind.setdefault(item.kind, []).append(item)

        facts: list[dict] = []
        hypotheses: list[dict] = []
        missing: list[str] = []
        next_checks: list[dict] = []

        def fact(text: str, items: list[EvidenceItem]) -> None:
            citations = [i.id for i in items if i.id][:3]
            if citations:
                facts.append({"text": text, "citations": citations})

        if by_kind.get("service"):
            item = by_kind["service"][0]
            status = item.data.get("status", "unknown")
            fact(f"Service status is reported as {status}.", [item])
            if status in ("down", "degraded"):
                next_checks.append(
                    {
                        "text": "Verify the failing endpoint manually from a controlled network.",
                        "rationale": "Automated health checks report a non-healthy state; a human check distinguishes service failure from checker/network failure.",
                    }
                )

        health = by_kind.get("health_check_result", [])
        if health:
            failures = [i for i in health if "pass" not in i.summary.lower()[:80]]
            fact(
                f"{len(health) - len(failures)} of the {len(health)} sampled health checks passed.",
                health[:3],
            )
            if failures:
                latest_failure = failures[-1]
                fact(
                    f"The most recent non-passing health check reported: {latest_failure.summary}",
                    [latest_failure],
                )
        else:
            missing.append("No health-check results were recorded inside the incident window.")

        metrics = by_kind.get("metric", [])
        for metric in metrics:
            fact(metric.summary, [metric])

        logs = by_kind.get("log_event", [])
        if logs:
            errors = [
                i for i in logs if i.summary.startswith("[error]") or i.summary.startswith("[critical]")
            ]
            if errors:
                fact(
                    f"{len(errors)} of the {len(logs)} sampled log events are error or critical severity.",
                    errors[:3],
                )
                next_checks.append(
                    {
                        "text": "Filter logs to error/critical for this service and widen the time range slightly.",
                        "rationale": "Sampled errors are present; the first error often precedes the first failed health check.",
                    }
                )
            else:
                fact(
                    "Sampled logs contain no error or critical events in the window.",
                    logs[:2],
                )
                missing.append(
                    "No error-level application logs in the window; the failure may not be logged at error severity."
                )
        else:
            missing.append(
                "No application logs in the window. Connect log ingestion for this service to improve correlation."
            )

        webhooks = by_kind.get("webhook_event", [])
        if webhooks:
            latest = webhooks[-1]
            fact(f"A verified source-control event was recorded: {latest.summary}", [latest])
            deployment_like = [
                i for i in webhooks if "deployment" in i.summary.lower() or i.kind == "webhook_event"
            ]
            if deployment_like and health:
                hypotheses.append(
                    {
                        "text": "A recent change may be related to the observed degradation.",
                        "reasoning": (
                            "A verified source-control event occurred inside the incident window and "
                            "health checks are not passing, but temporal proximity is not causation."
                        ),
                        "confidence": "medium",
                        "citations": [deployment_like[-1].id] + [health[-1].id],
                    }
                )
        else:
            missing.append(
                "No verified repository or deployment events in the window; release correlation is unavailable."
            )

        alerts = by_kind.get("alert", [])
        for alert in alerts[:2]:
            fact(alert.summary, [alert])

        if not facts:
            facts.append(
                {
                    "text": "No operational evidence was available to summarise.",
                    "citations": [],
                }
            )

        if not health:
            hypotheses.append(
                {
                    "text": "The reported incident may be driven by a non-HTTP failure mode.",
                    "reasoning": "No HTTP health-check results exist, so availability cannot be derived from them.",
                    "confidence": "low",
                    "citations": [i.id for i in logs[:1]],
                }
            )

        if len(facts) >= 3 and not hypotheses:
            hypotheses.append(
                {
                    "text": "The incident may be a contained, single-service degradation.",
                    "reasoning": "The sampled evidence concerns one service and no cross-service signal is present.",
                    "confidence": "low",
                    "citations": [i.id for i in (health[:1] + logs[:1] + alerts[:1]) if i.id],
                }
            )

        if not missing:
            missing.append("No additional missing information identified from the available evidence.")

        next_checks.extend(
            [
                {
                    "text": "Confirm whether the incident started before or after the most recent deployment.",
                    "rationale": "A timeline comparison is the cheapest way to accept or reject the deployment hypothesis.",
                },
                {
                    "text": "Compare the failing time window with the service's error-rate baseline.",
                    "rationale": "A spike relative to baseline indicates a new failure; a flat line indicates persistent debt.",
                },
            ]
        )
        if alerts:
            next_checks.append(
                {
                    "text": "Review the alert rule's threshold and window against recent alert usefulness.",
                    "rationale": "Alert quality affects whether responders trust the signal.",
                }
            )

        deduped_checks: list[dict] = []
        seen: set[str] = set()
        for check in next_checks:
            if check["text"] not in seen:
                seen.add(check["text"])
                deduped_checks.append(check)

        return AdapterResult(
            output={
                "observed_facts": facts[:8],
                "hypotheses": hypotheses[:4],
                "missing_information": missing[:6],
                "recommended_next_checks": deduped_checks[:6],
            },
            provider=self.name,
            model_id="rules-v1",
        )


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _extract_json(content: str) -> dict:
    content = content.strip()
    match = _JSON_BLOCK.search(content)
    if match:
        content = match.group(1)
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model did not return a JSON object")
    return json.loads(content[start : end + 1])


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def analyze(self, payload: PromptPayload) -> AdapterResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "max_tokens": 1200,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": payload.system},
                        {"role": "user", "content": payload.user},
                    ],
                },
            )
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        return AdapterResult(
            output=_extract_json(content),
            provider=self.name,
            model_id=body.get("model", self.model),
        )


def get_adapter() -> AIAdapter:
    if settings.ai_provider == "openai_compatible" and settings.ai_api_key and settings.ai_model:
        return OpenAICompatibleAdapter(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout=settings.ai_timeout_seconds,
        )
    return LocalDeterministicAdapter()


__all__ = [
    "AIAdapter",
    "AdapterResult",
    "LocalDeterministicAdapter",
    "OpenAICompatibleAdapter",
    "get_adapter",
]
