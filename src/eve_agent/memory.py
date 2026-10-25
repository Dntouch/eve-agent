"""Language-neutral text primitives used at Memory database boundaries.

Persistent knowledge lives exclusively in SQLite. This module contains no
file-backed store, bundled facts, vocabulary, aliases or domain meanings.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass


_SECRET_NAMES = (
    r"local[\s_-]?key|access[\s_-]?token|refresh[\s_-]?token|api[\s_-]?key|"
    r"client[\s_-]?secret|password|passwort|passwd|secret|token"
)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)(\b(?:{_SECRET_NAMES})\b\s*(?:[:=]|\b(?:is|ist|lautet)\b)\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;\r\n]+)"
)
_AUTHORIZATION = re.compile(
    r"(?i)(\bAuthorization\s*:\s*)(?:Bearer\s+|Basic\s+)?[^\s,;\r\n]+"
)
_BEARER = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
_JWT_CREDENTIAL = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)
_SECRET_CONTINUATION = re.compile(
    rf"(?i)\b(?:{_SECRET_NAMES}|Authorization|Bearer|Basic|local|access|refresh|api|client)\b"
    r"\s*(?:(?:[:=]|is|ist|lautet)\s*)?$"
)


def redact_sensitive(text: str) -> str:
    """Remove credentials before text reaches logs, Memory or an LLM."""
    if not isinstance(text, str):
        return text
    cleaned = _AUTHORIZATION.sub(r"\1[REDACTED]", text)
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", cleaned)
    cleaned = _BEARER.sub(r"\1[REDACTED]", cleaned)
    from .transient_credentials import redact_transient
    return redact_transient(_JWT_CREDENTIAL.sub("[REDACTED]", cleaned))


class RedactedTextStream:
    """Apply the storage redactor before publication, across arbitrary chunks.

    Keep an unfinished line (and a trailing credential introducer) private until
    its value is known. No length cutoff or token guessing is involved.
    """

    def __init__(self, publish):
        self.publish = publish
        self.pending = ""

    def feed(self, chunk: str) -> None:
        self.pending += chunk
        boundary = self.pending.rfind("\n") + 1
        if not boundary:
            return
        complete = self.pending[:boundary]
        if _SECRET_CONTINUATION.search(complete):
            return
        self.publish(redact_sensitive(complete))
        self.pending = self.pending[boundary:]

    def finish(self) -> None:
        if self.pending:
            self.publish(redact_sensitive(self.pending))
            self.pending = ""

    def reset(self) -> None:
        self.pending = ""


def lexical_tokens(text: str) -> set[str]:
    """Return normalized tokens without a language-specific vocabulary."""
    normalized = unicodedata.normalize("NFKD", str(text).casefold())
    return {
        word for word in re.findall(r"[^\W_]+", normalized, re.UNICODE)
        if len(word) > 2
    }


def lexical_vector(text: str, dimensions: int = 256) -> list[float]:
    """Create a deterministic word/character fingerprint without meanings."""
    normalized = unicodedata.normalize("NFKD", str(text).casefold())
    words = list(lexical_tokens(normalized))
    features = [f"w:{word}" for word in words]
    compact = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    features.extend(
        f"g:{word[index:index + 3]}"
        for word in compact.split()
        for index in range(max(0, len(word) - 2))
    )
    vector = [0.0] * dimensions
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += (
            1.0 if digest[4] & 1 else -1.0
        )
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


@dataclass
class MemoryHit:
    text: str
    score: float
    memory_id: str | None = None
    method: str = "unknown"
    compiler_evaluation_id: str | None = None
