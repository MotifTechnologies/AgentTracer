"""Every bundled MCP server's manifest must match what its code implements.

The manifest's ``tools`` list is what the repo documents and what contract
checks read; the ``@mcp.tool()`` functions are what the agent actually gets.
When those drift, a tool silently appears in or disappears from the trajectory
tool distribution — the same class of failure the discovery fail-fast exists to
prevent, except no run ever errors.

Read statically: the servers each declare their own dependencies (pypdf,
openpyxl, ...) and run under a separate interpreter, so importing or spawning
them here would drag the whole set into the test environment.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agent_tracer.config.schema import MCPDiscoveryConfig
from agent_tracer.mcp.discovery import MCPManifest, discover_mcp_servers

SERVER_ROOT = MCPDiscoveryConfig().resolved_discovery_dir()
MANIFESTS = sorted(SERVER_ROOT.glob("*/mcp.json"))


def _implemented_tools(server_py: Path) -> set[str]:
    """Names of ``@mcp.tool()``-decorated functions, without importing."""
    tree = ast.parse(server_py.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                # `@mcp.tool(name="x")` would rename it; honour that if used.
                renamed = next(
                    (
                        kw.value.value
                        for kw in (call.keywords if call else [])
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant)
                    ),
                    None,
                )
                names.add(renamed or node.name)
    return names


def test_manifests_exist():
    assert MANIFESTS, f"no MCP manifests found under {SERVER_ROOT}"


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda p: p.parent.name)
class TestManifestMatchesImplementation:
    def test_manifest_declares_its_tools(self, manifest_path: Path):
        manifest = MCPManifest.model_validate(
            json.loads(manifest_path.read_text("utf-8"))
        )
        assert manifest.tools, (
            f"{manifest.name}: manifest declares no tools — the inventory and the "
            "contract check both read this list"
        )
        for tool in manifest.tools:
            assert tool.description.strip(), (
                f"{manifest.name}.{tool.name}: empty description"
            )

    def test_declared_tools_match_implemented_tools(self, manifest_path: Path):
        manifest = MCPManifest.model_validate(
            json.loads(manifest_path.read_text("utf-8"))
        )
        server_py = manifest_path.parent / "server.py"
        if not server_py.is_file():
            # An HTTP server we point at rather than write; nothing local to compare.
            assert manifest.transport == "http", (
                f"{manifest.name}: stdio server has no server.py"
            )
            pytest.skip(f"{manifest.name} is hosted elsewhere")

        declared = {tool.name for tool in manifest.tools}
        implemented = _implemented_tools(server_py)
        assert declared == implemented, (
            f"{manifest.name}: manifest and server.py disagree — "
            f"declared only: {sorted(declared - implemented)}, "
            f"implemented only: {sorted(implemented - declared)}"
        )


def test_every_server_directory_is_discoverable():
    """Discovery must register exactly the directories that ship a manifest."""
    discovered = discover_mcp_servers(MCPDiscoveryConfig())
    assert set(discovered) == {p.parent.name for p in MANIFESTS}
