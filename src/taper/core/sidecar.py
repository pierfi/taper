"""Read/write the `<stem>.taper.json` sidecar that sits next to a downloaded audio file."""

from __future__ import annotations

import json
from pathlib import Path

from taper.errors import SourceError
from taper.models import SourceInfo

SIDECAR_SUFFIX = ".taper.json"


def sidecar_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + SIDECAR_SUFFIX)


def save_sidecar(info: SourceInfo, audio: Path) -> Path:
    """Write the sidecar atomically (`.part` then rename)."""
    target = sidecar_path(audio)
    tmp = target.with_name(target.name + ".part")
    tmp.write_text(json.dumps(info.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def load_sidecar(audio: Path) -> SourceInfo | None:
    """Sidecar of `audio`, or None for local files that never went through `fetch`."""
    path = sidecar_path(audio)
    if not path.exists():
        return None
    try:
        return SourceInfo.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError, KeyError) as exc:
        raise SourceError(f"Sidecar non valido: {path} ({exc})") from exc
