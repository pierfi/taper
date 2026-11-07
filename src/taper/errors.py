"""Errors raised by the core. The CLI turns them into friendly messages."""

from __future__ import annotations


class TaperError(Exception):
    """Base error: a message plus an optional hint on how to fix it."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ToolNotFoundError(TaperError):
    """An external tool (ffmpeg, ffprobe) is missing."""


class SourceError(TaperError):
    """Download/input problems: unsupported URL, unreadable file."""


class InvalidPlanError(TaperError):
    """The cut plan is invalid. `problems` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(
            "Piano di taglio non valido:\n" + "\n".join(f"  - {p}" for p in problems),
            "Correggi il file YAML del piano e riprova.",
        )
        self.problems = problems
