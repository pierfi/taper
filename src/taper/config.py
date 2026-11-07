"""Where the library lives. No config file: option > environment variable > default."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from taper.errors import TaperError

ENV_LIBRARY = "TAPER_LIBRARY"
ENV_ALLOW_WINDOWS = "TAPER_ALLOW_WINDOWS_PATHS"

# Temporary default: inside the Linux filesystem (WSL home), never on a Windows drive.
DEFAULT_LIBRARY = Path.home() / "taper-library"


def is_windows_mount(path: Path) -> bool:
    """True for WSL paths on a Windows drive, e.g. /mnt/c/Users/... (pure)."""
    parts = path.parts
    return (
        len(parts) >= 3
        and parts[0] == "/"
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    )


def ensure_library_allowed(root: Path, env: Mapping[str, str] | None = None) -> None:
    """Refuse a library on a Windows drive unless explicitly allowed."""
    env = os.environ if env is None else env
    real = Path(os.path.realpath(root))
    if is_windows_mount(real) and env.get(ENV_ALLOW_WINDOWS) != "1":
        raise TaperError(
            f"La libreria sarebbe su un disco Windows ({real}).",
            f"Scegli una cartella nel filesystem Linux (default: {DEFAULT_LIBRARY}); "
            f"per consentirlo davvero imposta {ENV_ALLOW_WINDOWS}=1.",
        )


def resolve_library(option: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    """Library root: `--library` > $TAPER_LIBRARY > default. Not created, only checked."""
    env = os.environ if env is None else env
    if option is not None:
        root = option
    elif env.get(ENV_LIBRARY):
        root = Path(env[ENV_LIBRARY])
    else:
        root = DEFAULT_LIBRARY
    root = root.expanduser().absolute()
    ensure_library_allowed(root, env)
    return root
