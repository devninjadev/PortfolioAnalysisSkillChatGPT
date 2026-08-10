"""Deterministic data gates for the evidence-first portfolio skill."""

from __future__ import annotations

from typing import Any


class DataGateError(RuntimeError):
    """Raised when evidence is insufficient for the requested calculation."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


__all__ = ["DataGateError"]
