"""Removing credentials from what the platform writes for people to read: activity events, errors of agent
invocations, logs and the exported JSON of an event (spec 18.8). Values that look like a credential become
`[REDACTED]`; so does anything under a key whose name says it holds one."""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-(?:or-|ant-|proj-)?[A-Za-z0-9_-]{16,}"),  # OpenRouter, Anthropic, OpenAI style keys
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"(?i)\b(?:bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{12,}"),
)
# user:password@ in URLs keeps the user and the host.
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^@\s/]+@")
# key=value and "key": "value" where the key names a credential.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|token|
        authorization|private[_-]?key)\b["']?\s*[:=]\s*)
    ("[^"]*"|'[^']*'|[^\s,;&"'}]+)
    """
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token|authorization|credential|private[_-]?key|cookie)"
)


def redact_text(value: str) -> str:
    for pattern in _PATTERNS:
        value = pattern.sub(REDACTED, value)
    value = _URL_CREDENTIALS.sub(rf"\1:{REDACTED}@", value)
    return _ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, value)


def redact(value: Any) -> Any:
    """A copy of `value` (JSON-like: dicts, lists, strings, numbers) without credentials."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(k): (REDACTED if _SENSITIVE_KEY.search(str(k)) and v not in (None, "") else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value
