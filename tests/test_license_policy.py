"""Regression cases for the CI license gate and MCP inventory coverage."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / ".github/scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load("check_licenses")
builder = load("build_sbom")


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("MIT", "allowed"),
        ("MIT AND GPL-3.0-only", "blocked"),
        ("(MIT OR Apache-2.0) AND GPL-3.0-only", "blocked"),
        ("MIT OR (Apache-2.0 AND GPL-3.0-only)", "allowed"),
        ("MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later", "allowed"),
        ("GPL-2.0-only WITH Classpath-exception-2.0", "blocked"),
        ("LicenseRef-MIT-Custom-Restrictions", "unknown"),
        ("licenseref-mit-bootstrap", "unknown"),
        ("MIT OR LicenseRef-MIT-Custom", "unknown"),
        ("MIT AND", "unknown"),
        ("", "unknown"),
    ],
)
def test_spdx_policy(expression, expected):
    assert policy.expression_verdict(expression) == expected


def component(licenses):
    return {"name": "example", "version": "1.0", "licenses": licenses}


def test_distinct_licenses_are_not_implicit_or():
    result, _ = policy.component_verdict(
        component(
            [
                {"license": {"id": "MIT"}},
                {"license": {"id": "GPL-3.0-only"}},
            ]
        )
    )
    assert result == "blocked"


def test_missing_license_and_custom_name_need_review():
    for licenses in ([], [{"license": {"name": "MIT with extra restrictions"}}]):
        assert policy.component_verdict(component(licenses))[0] == "unknown"


def test_license_attachment_does_not_hide_missing_declaration():
    assert (
        policy.component_verdict(
            component(
                [
                    {
                        "license": {
                            "name": "declared license file: LICENSE",
                            "text": {"content": "MIT"},
                        }
                    },
                ]
            )
        )[0]
        == "unknown"
    )


def test_legacy_declaration_and_evidence_are_preserved():
    result, declarations = policy.component_verdict(
        component(
            [
                {
                    "license": {
                        "name": "declared license of 'example'",
                        "text": {"content": "Apache License 2.0"},
                    }
                },
            ]
        )
    )
    assert result == "allowed"
    assert declarations[0]["normalized"] == "Apache-2.0"


def test_invalid_bom_is_not_clean_inventory():
    for bom in ({}, {"bomFormat": "CycloneDX", "components": []}):
        with pytest.raises(ValueError):
            policy.check_bom(bom, "fixture")


def test_uncovered_mcp_launch_fails(tmp_path):
    folder = tmp_path / "src/agent_tracer/mcp_servers/new"
    folder.mkdir(parents=True)
    (folder / "mcp.json").write_text(
        json.dumps({"name": "new", "transport": "stdio", "command": "npx", "args": []})
    )
    with pytest.raises(ValueError, match="unsupported launch"):
        builder.mcp_scripts(tmp_path)


def test_missing_mcp_lock_fails(tmp_path):
    folder = tmp_path / "src/agent_tracer/mcp_servers/new"
    folder.mkdir(parents=True)
    (folder / "mcp.json").write_text(
        json.dumps(
            {
                "name": "new",
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "--quiet", "server.py"],
            }
        )
    )
    (folder / "server.py").write_text("# /// script\n# dependencies = []\n# ///\n")
    with pytest.raises(ValueError, match="missing script or lockfile"):
        builder.mcp_scripts(tmp_path)


def test_reviewed_metadata_needs_exact_version_and_license_text():
    sample = {"name": "python-dateutil", "version": "2.9.0.post0", "licenses": []}
    assert policy.reviewed_expression(sample, "Dual License") == "Dual License"
    sample["licenses"] = [{"license": {"text": {"content": "modified license"}}}]
    assert policy.reviewed_expression(sample, "Dual License") == "Dual License"


def test_reviewed_metadata_accepts_only_pinned_evidence(monkeypatch):
    digest = hashlib.sha256(b"fixture license").hexdigest()
    monkeypatch.setattr(
        policy, "REVIEWED_TEXTS", {("example", "1.0", "custom"): (digest, "MIT")}
    )
    sample = component([{"license": {"text": {"content": "fixture license"}}}])
    assert policy.reviewed_expression(sample, "custom") == "MIT"
    sample["version"] = "2.0"
    assert policy.reviewed_expression(sample, "custom") == "custom"


def test_generic_dependency_license_declaration_stays_unknown():
    sample = {
        "name": "pypdfium2",
        "version": "5.13.0",
        "licenses": [
            {
                "license": {
                    "name": "declared license of 'pypdfium2'",
                    "text": {
                        "content": "BSD-3-Clause, Apache-2.0, dependency licenses",
                    },
                }
            },
        ],
    }
    assert policy.component_verdict(sample)[0] == "unknown"
