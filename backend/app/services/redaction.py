"""Secret and personal-data redaction applied before persistence.

Rules are conservative by design: a redacted value costs debugging convenience, a
leaked credential or personal datum cannot be un-leaked. Everything here is pure
and unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MASK = "[REDACTED]"

#: Keys whose values are always replaced wholesale.
SENSITIVE_KEY_PATTERNS = (
    re.compile(r"pass(word|wd|phrase)?", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"token", re.I),
    re.compile(r"api[-_]?key", re.I),
    re.compile(r"client[-_]?secret", re.I),
    re.compile(r"^auth(orization)?$", re.I),
    re.compile(r"^cookie$", re.I),
    re.compile(r"set[-_]?cookie", re.I),
    re.compile(r"private[-_]?key", re.I),
    re.compile(r"credential", re.I),
    re.compile(r"session[-_]?id", re.I),
    re.compile(r"^otp$", re.I),
)

_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer_token", re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/-]{16,}=*")),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("operation_zero_key", re.compile(r"\bozk_[A-Za-z0-9_-]{20,}\b")),
    (
        "keyed_secret",
        re.compile(
            r"(?i)\b(pass(?:word|wd)?|secret|token|api[-_]?key|client[-_]?secret|"
            r"authorization|auth|password_hash)\b\s*[:=]\s*[\"']?([^\s,;\"']{3,})[\"']?"
        ),
    ),
    (
        "url_credentials",
        re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?|amqp)://[^\s:/@]+:[^\s@]+@"),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "card_number",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
)

DEFAULT_REDACT_EMAILS = True
DEFAULT_REDACT_CARD_NUMBERS = True


@dataclass
class RedactionReport:
    count: int = 0
    fields: list[str] = field(default_factory=list)

    def merged(self, other: RedactionReport) -> RedactionReport:
        fields = list(dict.fromkeys(self.fields + other.fields))
        return RedactionReport(count=self.count + other.count, fields=fields)


def _key_is_sensitive(key: str) -> bool:
    return any(pattern.search(key) for pattern in SENSITIVE_KEY_PATTERNS)


def _redact_string(value: str, report: RedactionReport, *path: str) -> str:
    for name, pattern in _VALUE_PATTERNS:
        if name == "email" and not DEFAULT_REDACT_EMAILS:
            continue
        if name == "card_number" and not DEFAULT_REDACT_CARD_NUMBERS:
            continue

        def mark() -> None:
            report.count += 1
            label_path = ".".join(path) or "message"
            if label_path not in report.fields:
                report.fields.append(label_path)

        if name == "keyed_secret":

            def _keyed(match: re.Match[str]) -> str:
                mark()
                return f"{match.group(1)}={MASK}"

            value = pattern.sub(_keyed, value)
        else:

            def _replace(_match: re.Match[str]) -> str:
                mark()
                return MASK

            value = pattern.sub(_replace, value)
    return value


def redact_value(value: Any, report: RedactionReport, *path: str) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _key_is_sensitive(key_str):
                report.count += 1
                field_path = ".".join((*path, key_str))
                report.fields.append(field_path)
                result[key_str] = MASK
            else:
                result[key_str] = redact_value(item, report, *path, key_str)
        return result
    if isinstance(value, list):
        return [redact_value(item, report, *path, str(index)) for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [redact_value(item, report, *path, str(index)) for index, item in enumerate(value)]
    if isinstance(value, str):
        return _redact_string(value, report, *path)
    if isinstance(value, bytes):
        return MASK
    return value


def redact(message: str, attributes: dict | None = None) -> tuple[str, dict, RedactionReport]:
    """Redact a log message and its structured attributes."""
    report = RedactionReport()
    safe_message = _redact_string(message, report, "message")
    safe_attributes = redact_value(attributes or {}, report, "attributes")
    return safe_message, safe_attributes, report


def redact_dict(payload: dict) -> tuple[dict, RedactionReport]:
    report = RedactionReport()
    return redact_value(payload, report), report


__all__ = [
    "MASK",
    "RedactionReport",
    "redact",
    "redact_value",
    "redact_dict",
    "SENSITIVE_KEY_PATTERNS",
]
