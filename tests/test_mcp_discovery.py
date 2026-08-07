import json
import os
from pathlib import Path

import pytest

import agent_tracer
from agent_tracer.config.schema import ConfigError, MCPDiscoveryConfig
from agent_tracer.mcp.discovery import build_stirrup_mcp_config, discover_mcp_servers


def _server(root: Path, name: str, **overrides) -> Path:
    manifest = {
        "manifest_version": 1,
        "name": name,
        "description": f"{name} test server",
        "transport": "stdio",
        "command": "uv",
        "args": ["run", "server.py"],
    }
    manifest.update(overrides)
    d = root / name
    d.mkdir(parents=True)
    (d / "mcp.json").write_text(json.dumps(manifest))
    return d


def _cfg(root: Path, **kw) -> MCPDiscoveryConfig:
    return MCPDiscoveryConfig(discovery_dir=root, **kw)


class TestDiscovery:
    def test_default_all(self, tmp_path):
        _server(tmp_path, "alpha")
        _server(tmp_path, "beta")
        assert sorted(discover_mcp_servers(_cfg(tmp_path))) == ["alpha", "beta"]

    def test_include_narrows(self, tmp_path):
        _server(tmp_path, "alpha")
        _server(tmp_path, "beta")
        assert list(discover_mcp_servers(_cfg(tmp_path, include=["beta"]))) == ["beta"]

    def test_exclude_removes(self, tmp_path):
        _server(tmp_path, "alpha")
        _server(tmp_path, "beta")
        assert list(discover_mcp_servers(_cfg(tmp_path, exclude=["beta"]))) == ["alpha"]

    def test_unknown_include_fails_fast(self, tmp_path):
        _server(tmp_path, "alpha")
        with pytest.raises(ConfigError, match="include names"):
            discover_mcp_servers(_cfg(tmp_path, include=["nope"]))

    def test_missing_manifest_fails_fast(self, tmp_path):
        (tmp_path / "broken").mkdir()
        with pytest.raises(ConfigError, match="no mcp.json"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_name_dir_mismatch_fails_fast(self, tmp_path):
        d = _server(tmp_path, "alpha")
        manifest = json.loads((d / "mcp.json").read_text())
        manifest["name"] = "omega"
        (d / "mcp.json").write_text(json.dumps(manifest))
        with pytest.raises(ConfigError, match="does not match directory"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_invalid_json_fails_fast(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "mcp.json").write_text("{not json")
        with pytest.raises(ConfigError, match="invalid manifest"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_http_requires_url(self, tmp_path):
        _server(tmp_path, "web", transport="http")
        with pytest.raises(ConfigError, match="url"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_env_ref_resolution_fails_fast(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AT_MISSING_SECRET", raising=False)
        _server(tmp_path, "alpha", env={"KEY": "env:AT_MISSING_SECRET"})
        with pytest.raises(ConfigError, match="AT_MISSING_SECRET"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_packaged_default_discovers_echo(self):
        manifests = discover_mcp_servers(MCPDiscoveryConfig())
        assert "echo" in manifests


class TestStirrupMapping:
    def test_stdio_maps_with_cwd(self, tmp_path):
        _server(tmp_path, "alpha")
        manifests = discover_mcp_servers(_cfg(tmp_path))
        mcp_config = build_stirrup_mcp_config(manifests, tmp_path)
        server = mcp_config.mcp_servers["alpha"]
        assert server.command == "uv"
        assert server.cwd == str((tmp_path / "alpha").resolve())

    def test_a_manifest_adds_to_pythonpath_rather_than_replacing_it(self, tmp_path):
        """The package path is what lets a spawned server import the package it
        was spawned by — `environments.from_env()` is the first line of every
        sandbox-bound server. A manifest naming its own PYTHONPATH took that
        away entirely, and the server could not start."""
        _server(tmp_path, "alpha", env={"PYTHONPATH": "/opt/vendor/lib"})
        manifests = discover_mcp_servers(_cfg(tmp_path))

        env = build_stirrup_mcp_config(manifests, tmp_path).mcp_servers["alpha"].env

        entries = env["PYTHONPATH"].split(os.pathsep)
        assert "/opt/vendor/lib" in entries, env
        assert str(Path(agent_tracer.__file__).resolve().parent.parent) in entries, env

    def test_the_sandbox_description_is_still_a_manifest_s_to_override(self, tmp_path):
        _server(tmp_path, "alpha", env={"AGENT_TRACER_ENV_TYPE": "local"})
        manifests = discover_mcp_servers(_cfg(tmp_path))

        env = build_stirrup_mcp_config(
            manifests, tmp_path, {"AGENT_TRACER_ENV_TYPE": "docker"}
        ).mcp_servers["alpha"].env

        assert env["AGENT_TRACER_ENV_TYPE"] == "local"


class TestHttpServers:
    """`headers` is where a hosted server's API key goes, so it gets the same
    `env:` discipline as `env` — a key written into a manifest is a key
    published with the repository."""

    def test_env_refs_in_headers_are_resolved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_DOCS_KEY", "secret-value")
        _server(tmp_path, "docs", transport="http", url="https://example.test/mcp",
                headers={"Authorization": "env:TEST_DOCS_KEY", "X-Fixed": "literal"},
                command=None, args=[])
        manifests = discover_mcp_servers(_cfg(tmp_path))

        cfg = build_stirrup_mcp_config(manifests, tmp_path)

        headers = cfg.mcp_servers["docs"].headers
        assert headers == {"Authorization": "secret-value", "X-Fixed": "literal"}

    def test_an_unset_ref_refuses_to_run(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
        _server(tmp_path, "docs", transport="http", url="https://example.test/mcp",
                headers={"Authorization": "env:TEST_MISSING_KEY"}, command=None, args=[])
        manifests = discover_mcp_servers(_cfg(tmp_path))

        with pytest.raises(ConfigError, match="TEST_MISSING_KEY"):
            build_stirrup_mcp_config(manifests, tmp_path)

    def test_headers_are_rejected_on_stdio(self, tmp_path):
        """They would be silently ignored otherwise."""
        _server(tmp_path, "local", headers={"Authorization": "x"})

        with pytest.raises(ConfigError, match="http transport only"):
            discover_mcp_servers(_cfg(tmp_path))

    def test_call_timeout_carries_to_the_http_client(self, tmp_path):
        _server(tmp_path, "docs", transport="http", url="https://example.test/mcp",
                call_timeout_s=42, command=None, args=[])
        manifests = discover_mcp_servers(_cfg(tmp_path))

        assert build_stirrup_mcp_config(manifests, tmp_path).mcp_servers["docs"].timeout == 42
