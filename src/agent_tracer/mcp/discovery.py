"""MCP/ directory auto-discovery.

Every subdirectory of the discovery dir holding an ``mcp.json`` manifest is an
MCP server. All discovered servers are registered by default (default all);
YAML ``mcp.include`` / ``mcp.exclude`` narrows the set. A missing or invalid
manifest aborts the run — a silently absent tool would corrupt the generated
dataset's tool distribution (fail-fast, same policy as api_key/reasoning_key).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from agent_tracer.config.schema import ConfigError, MCPDiscoveryConfig, resolve_env_ref


class ManifestTool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str


class MCPManifest(BaseModel):
    """Schema for MCP/<name>/mcp.json (manifest_version 1)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = None
    manifest_version: Literal[1]
    name: str
    description: str
    version: str | None = None
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] = {}
    startup_timeout_s: float = 15
    call_timeout_s: float = 60
    tools: list[ManifestTool] = []

    @model_validator(mode="before")
    @classmethod
    def _alias_schema(cls, data: Any) -> Any:
        if isinstance(data, dict) and "$schema" in data:
            data = dict(data)
            data["schema_ref"] = data.pop("$schema")
        return data

    @model_validator(mode="after")
    def _transport_fields(self) -> MCPManifest:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError("http transport requires 'url'")
        return self


def discover_mcp_servers(config: MCPDiscoveryConfig) -> dict[str, MCPManifest]:
    """Scan the discovery dir and return the selected server manifests."""
    root = config.resolved_discovery_dir()
    if not root.is_dir():
        if config.include:
            raise ConfigError(
                f"mcp: include={config.include} requested but discovery dir {root} does not exist"
            )
        return {}

    manifests: dict[str, MCPManifest] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "mcp.json"
        if not manifest_path.is_file():
            raise ConfigError(
                f"mcp: {child} has no mcp.json manifest — every directory under "
                f"{root}/ must be a valid MCP server (fail-fast)"
            )
        import json

        try:
            manifest = MCPManifest.model_validate(json.loads(manifest_path.read_text("utf-8")))
        except (ValidationError, json.JSONDecodeError) as e:
            raise ConfigError(f"mcp: invalid manifest {manifest_path}:\n{e}") from e
        if manifest.name != child.name:
            raise ConfigError(
                f"mcp: manifest name {manifest.name!r} does not match directory {child.name!r}"
            )
        manifests[manifest.name] = manifest

    selected = _select(manifests, config)

    # Resolve env: references now so a missing secret aborts before any task runs.
    for manifest in selected.values():
        for var, value in manifest.env.items():
            if value.startswith("env:"):
                resolve_env_ref(value, field=f"mcp[{manifest.name}].env.{var}")
    return selected


def _select(
    manifests: dict[str, MCPManifest], config: MCPDiscoveryConfig
) -> dict[str, MCPManifest]:
    if config.include is not None:
        missing = set(config.include) - manifests.keys()
        if missing:
            raise ConfigError(
                f"mcp: include names {sorted(missing)} not found in {config.resolved_discovery_dir()}/ "
                f"(available: {sorted(manifests)})"
            )
        return {n: manifests[n] for n in config.include}
    if config.exclude is not None:
        unknown = set(config.exclude) - manifests.keys()
        if unknown:
            raise ConfigError(
                f"mcp: exclude names {sorted(unknown)} not found in {config.resolved_discovery_dir()}/ "
                f"(available: {sorted(manifests)})"
            )
        return {n: m for n, m in manifests.items() if n not in config.exclude}
    return manifests


def build_stirrup_mcp_config(manifests: dict[str, MCPManifest], root: Path):
    """Map selected manifests onto stirrup's MCPConfig for its native client."""
    from stirrup.tools.mcp import MCPConfig, StdioServerConfig, StreamableHttpServerConfig

    servers: dict[str, Any] = {}
    for name, m in manifests.items():
        if m.transport == "stdio":
            env = {
                var: (resolve_env_ref(val, field=f"mcp[{name}].env.{var}") if val.startswith("env:") else val)
                for var, val in m.env.items()
            }
            servers[name] = StdioServerConfig(
                command=m.command,
                args=m.args,
                env=env or None,
                cwd=str((root / name).resolve()),
            )
        else:
            servers[name] = StreamableHttpServerConfig(url=m.url)
    return MCPConfig.model_validate({"mcpServers": servers})
