"""CLI 冒烟测试：确保入口可加载、版本命令可用。"""

from typer.testing import CliRunner

from modou import __version__
from modou.cli import app


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
