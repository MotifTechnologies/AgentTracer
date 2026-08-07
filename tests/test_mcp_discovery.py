import json
import os
import shutil
import subprocess
import sys
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


class TestPackagePath:
    """What every stdio server is handed as PYTHONPATH.

    A server runs under its own `uv run` and declares `mcp>=2.0,<3`; the runner
    pins `mcp>=1.2,<2`. `uv run` inherits PYTHONPATH and places it ahead of the
    venv it builds for the script, so whatever is injected here shadows the
    server's own dependencies with the runner's. In this checkout the package's
    parent is `src/`, which holds nothing else and hides that entirely. Once the
    package is installed as a wheel it is site-packages, and every server dies
    on `from mcp.server import MCPServer` — with pydantic, httpx and anyio
    silently downgraded on the way.
    """

    def _installed(self, tmp_path: Path) -> Path:
        """A site-packages: this package, and the neighbours it lives among."""
        site_packages = tmp_path / "site-packages"
        package = Path(agent_tracer.__file__).resolve().parent
        shutil.copytree(package, site_packages / package.name)
        # `mcp` is the one that matters: the runner's is a major version below
        # what every server declares. It is empty here so that shadowing it in
        # this process is harmless — in a server it is fatal.
        for neighbour in ("mcp", "httpx"):
            (site_packages / neighbour).mkdir(parents=True)
            (site_packages / neighbour / "__init__.py").write_text("")
        return site_packages

    def _in(self, site_packages: Path, script: str) -> str:
        done = subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONPATH": str(site_packages)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def test_the_injected_directory_holds_agent_tracer_and_nothing_else(self, tmp_path):
        site_packages = self._installed(tmp_path)

        # Checked in the subprocess: the directory is this run's and is gone
        # once the runner that made it exits.
        listing = self._in(
            site_packages,
            "from pathlib import Path;"
            "from agent_tracer.mcp.discovery import _package_path;"
            "print(sorted(p.name for p in Path(_package_path()).iterdir()))",
        )

        assert listing == "['agent_tracer']"

    def test_the_package_is_importable_from_it(self, tmp_path):
        """Which is the whole reason it is injected: `environments.from_env()`
        is the first line of every sandbox-bound server."""
        site_packages = self._installed(tmp_path)

        found = self._in(
            site_packages,
            "import subprocess, sys, os;"
            "from agent_tracer.mcp.discovery import _package_path;"
            "print(subprocess.run([sys.executable, '-c', 'import agent_tracer'],"
            " env={'PATH': os.environ['PATH'], 'PYTHONPATH': _package_path()},"
            " capture_output=True).returncode)",
        )

        assert found == "0"


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
        assert [p.name for p in Path(entries[0]).iterdir()] == ["agent_tracer"], env

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
