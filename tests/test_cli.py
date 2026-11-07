from typer.testing import CliRunner

from taper import __version__
from taper.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_commands_registered():
    result = runner.invoke(app, ["--help"])
    for cmd in ("fetch", "plan", "cut", "run"):
        assert cmd in result.output
