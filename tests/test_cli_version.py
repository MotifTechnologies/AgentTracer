"""`agent-tracer --version` reports the installed distribution's version."""

from __future__ import annotations

import tomllib
from pathlib import Path

from click.testing import CliRunner

from agent_tracer.run.cli import installed_version, main

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_option_prints_the_installed_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"agent-tracer {installed_version()}\n"


def test_installed_version_matches_pyproject():
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    assert installed_version() == project["version"]
