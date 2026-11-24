"""The PyPI workflow publishes what the release tag says, and nothing else.

PyPI never lets a version be replaced, so a mistake here is permanent: the
token scope, the version check and the distribution name are pinned by test.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())


def test_distribution_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "motif-agent-tracer"
    # The command users type is unchanged by the distribution name.
    assert project["scripts"]["agent-tracer"] == "agent_tracer.run.cli:main"


def test_only_the_publish_job_can_mint_an_oidc_token():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    jobs = WORKFLOW["jobs"]
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["publish"]["environment"]["name"] == "pypi"
    assert "permissions" not in jobs["build"]


def test_build_checks_version_against_tag_before_building():
    names = [s.get("name") for s in WORKFLOW["jobs"]["build"]["steps"]]
    assert names.index("Check the package version matches the tag") < names.index(
        "Build sdist and wheel"
    )


def test_prereleases_are_not_published():
    assert "prerelease" in WORKFLOW["jobs"]["build"]["if"]
    assert WORKFLOW["jobs"]["publish"]["needs"] == "build"
