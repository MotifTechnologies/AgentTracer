"""The release SBOM must be the inventory the Security workflow checks.

The release job repeats the `licenses` job's steps at the release tag. If the
two drift apart, a release ships an SBOM produced some other way than the one
every PR is gated on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"


def _job(workflow: str, job: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def _setup_uv(job: dict) -> dict:
    return next(s for s in job["steps"] if s.get("uses", "").startswith("astral-sh/"))


def test_release_sbom_matches_the_licenses_job():
    licenses = _job("security.yml", "licenses")
    release = _job("release.yml", "sbom")

    assert _setup_uv(release) == _setup_uv(licenses)
    assert {"run": "uv sync --locked --dev --group compliance"} in release["steps"]
    for name in (
        "Generate runtime, development and MCP SBOMs",
        "Check SBOM license declarations",
    ):
        assert _step(release, name)["run"] == _step(licenses, name)["run"]


def test_release_scans_the_tag_and_alone_may_write():
    workflow = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    # PyYAML reads the bare `on` key as True.
    assert workflow[True]["release"] == {"types": ["published"]}
    assert workflow["permissions"] == {"contents": "read"}

    release = workflow["jobs"]["sbom"]
    assert release["permissions"] == {"contents": "write"}
    checkout = release["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "refs/tags/${{ env.TAG }}"


@pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("sha256sum"),
    reason="Packaging test requires bash and sha256sum (available in CI)",
)
def test_package_step_bundles_the_report_set(tmp_path: Path):
    sbom = tmp_path / "sbom"
    sbom.mkdir()
    names = [
        "runtime.cdx.json",
        "mcp-echo.cdx.json",
        "mcp-echo.requirements.txt",
        "index.json",
        "license-report.json",
    ]
    for name in names:
        (sbom / name).write_text("{}")
    (sbom / "environments").mkdir()  # never shipped

    script = _step(_job("release.yml", "sbom"), "Package the SBOM set")["run"]
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={"TAG": "v0.1.0", "PATH": os.environ["PATH"]},
        check=True,
    )

    out = sbom / "release"
    archive = out / "agent-tracer-v0.1.0-sbom.zip"
    assert sorted(p.name for p in out.iterdir()) == [
        archive.name,
        f"{archive.name}.sha256",
    ]
    assert sorted(zipfile.ZipFile(archive).namelist()) == sorted(names)
    check = subprocess.run(
        ["sha256sum", "-c", f"{archive.name}.sha256"],
        cwd=out,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
