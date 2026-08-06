import json
from pathlib import Path

import pytest

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
