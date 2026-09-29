"""Counting credentials found in uploaded text (spec 15.3). Only rule names and file paths are reported, never the
values; masking before content reaches a model happens with the agents (M3/M4)."""

import re
from collections import Counter
from dataclasses import dataclass, field

RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jdbc_password", re.compile(rb"jdbc:[^\s'\"]*[?;&]password=[^\s;&'\"]+", re.I)),
    ("connection_string_password", re.compile(rb"\b(?:password|pwd)\s*=\s*[^;\s'\"]{4,}\s*;", re.I)),
    (
        "assigned_secret",
        re.compile(
            rb"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*['\"][^'\"\s]{6,}['\"]", re.I
        ),
    ),
)
MAX_LISTED_FILES = 50


@dataclass
class SecretFindings:
    counts: Counter[str] = field(default_factory=Counter)
    files: list[str] = field(default_factory=list)

    def scan(self, text: bytes, path: str) -> None:
        found = False
        for name, pattern in RULES:
            hits = len(pattern.findall(text))
            if hits:
                self.counts[name] += hits
                found = True
        if found and len(self.files) < MAX_LISTED_FILES:
            self.files.append(path)

    def summary(self) -> dict[str, object]:
        return {"total": sum(self.counts.values()), "by_rule": dict(sorted(self.counts.items())), "files": self.files}
