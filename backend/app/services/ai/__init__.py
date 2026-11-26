"""AI investigation subpackage."""

from app.services.ai.adapters import AIAdapter, get_adapter
from app.services.ai.evidence import build_evidence_pack, sources_index
from app.services.ai.orchestrator import normalize_output, record_feedback, run_analysis
from app.services.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_prompt

__all__ = [
    "AIAdapter",
    "get_adapter",
    "build_evidence_pack",
    "sources_index",
    "run_analysis",
    "normalize_output",
    "record_feedback",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "build_prompt",
]
