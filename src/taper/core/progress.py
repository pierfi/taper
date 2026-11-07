"""Progress reporting and cancellation shared by every long-running core function.

The core never prints: it emits `ProgressEvent`s to an optional callback. The CLI
renders them; the future web UI will forward them to the browser.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from taper.errors import CancelledError


@dataclass(frozen=True)
class ProgressEvent:
    stage: str  # e.g. "download", "postprocess", "cut"
    fraction: float | None = None  # 0..1, None when unknown
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


def emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is not None:
        callback(event)


def check_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise CancelledError("Operazione annullata.")
