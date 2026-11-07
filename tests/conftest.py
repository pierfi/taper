import pytest

from taper.config import ENV_LIBRARY


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """No test may ever write to the real default library in the user's home."""
    monkeypatch.setenv(ENV_LIBRARY, str(tmp_path / "default-library"))
