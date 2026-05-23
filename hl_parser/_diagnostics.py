"""Structured diagnostic dataclass for parse warnings and errors."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParseDiagnostic:
    """A single diagnostic event during parsing.

    Attributes:
        section:  The parser section that generated this (e.g. 'TYPE', 'FUNC', 'POOL')
        offset:   Stream byte offset where the issue occurred (or -1 if unknown)
        severity: 'WARN' or 'ERROR'
        message:  Human-readable description
        recovery: Optional description of what recovery action was taken
    """
    section: str
    offset: int = -1
    severity: str = 'WARN'
    message: str = ''
    recovery: Optional[str] = None

    def to_dict(self) -> dict:
        """Return as plain dict for backward compat with parse_warnings format."""
        d: dict = {"tag": self.section, "message": self.message}
        if self.recovery:
            d["recovery"] = self.recovery
        if self.offset >= 0:
            d["offset"] = self.offset
        return d
