"""MCP/ directory auto-discovery.

Every subdirectory of the discovery dir holding an ``mcp.json`` manifest is an
MCP server. All discovered servers are registered by default (default all);
YAML ``mcp.include`` / ``mcp.exclude`` narrows the set. A missing or invalid
manifest aborts the run — a silently absent tool would corrupt the generated
dataset's tool distribution (fail-fast, same policy as api_key/reasoning_key).
"""

from __future__ import annotations

import json
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
    #: Sent with every request to an `http` server. Same `env:` discipline as
    #: `env`, because this is where a hosted server's API key goes and a key
    #: committed to a manifest is a key published with the repository.
    headers: dict[str, str] = {}
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
        if self.transport == "stdio" and self.headers:
            raise ValueError("'headers' applies to http transport only")
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


#: Environment variables the runner sets on every stdio server it spawns.
#:
#: A manifest is read once at startup; a sandbox is created per task. So a
#: server that works on the agent's files cannot learn from its manifest which
#: sandbox is this task's — there is nowhere to put a value that does not exist
#: yet. It arrives here instead, in terms no backend owns: a type, an id, and
#: whatever that backend needs to attach (see agent_tracer.environments).
#:
#: Set on every server rather than opted into per manifest, so a new one can
#: rely on them being present. A server that only computes ignores them.
SANDBOX_ENV_PREFIX = "AGENT_TRACER_"

SANDBOX_ENV_VARS = (
    "AGENT_TRACER_ENV_TYPE",  # environment.type the sandbox was created under
    "AGENT_TRACER_SANDBOX_ID",  # what environments.attach() takes; absent for local
    "AGENT_TRACER_WORKDIR",  # the agent's working directory, inside the sandbox
    "AGENT_TRACER_HOST_DIR",  # host path the sandbox mounts, where it mounts one
    "AGENT_TRACER_USER",  # in-sandbox user, where the backend has one
    "AGENT_TRACER_OPTIONS",  # JSON: backend extras, passed to attach() untouched
)


def _package_path() -> str:
    """Where `agent_tracer` is importable from.

    A server that works on the agent's files calls `environments.attach()`
    rather than branching on backend, so it has to import this package — and it
    runs under its own `uv run`, which does not inherit the runner's
    interpreter. Passing the path is what lets a server stay declared with only
    the dependencies it uses itself.
    """
    import agent_tracer

    return str(Path(agent_tracer.__file__).resolve().parent.parent)


def sandbox_env(
    *,
    env_type: str,
    sandbox_id: str | None = None,
    workdir: str | None = None,
    host_dir: str | None = None,
    user: str | None = None,
    options: dict[str, str] | None = None,
) -> dict[str, str]:
    """Describe this task's sandbox for the servers about to be spawned.

    Empty values are dropped rather than passed as "", so a server tests for
    presence instead of for emptiness.
    """
    values = {
        "AGENT_TRACER_ENV_TYPE": env_type,
        "AGENT_TRACER_SANDBOX_ID": sandbox_id,
        "AGENT_TRACER_WORKDIR": workdir,
        "AGENT_TRACER_HOST_DIR": host_dir,
        "AGENT_TRACER_USER": user,
        "AGENT_TRACER_OPTIONS": json.dumps(options) if options else None,
    }
    return {k: v for k, v in values.items() if v}


def build_stirrup_mcp_config(
    manifests: dict[str, MCPManifest],
    root: Path,
    sandbox: dict[str, str] | None = None,
):
    """Map selected manifests onto stirrup's MCPConfig for its native client.

    `sandbox` is merged into every stdio server's environment. A manifest can
    override any of it; none of it is secret, and a server that should be
    pinned to one sandbox ought to be able to say so.
    """
    from stirrup.tools.mcp import MCPConfig, StdioServerConfig, StreamableHttpServerConfig

    servers: dict[str, Any] = {}
    for name, m in manifests.items():
        if m.transport == "stdio":
            env = {
                var: (resolve_env_ref(val, field=f"mcp[{name}].env.{var}") if val.startswith("env:") else val)
                for var, val in m.env.items()
            }
            # Manifest last: a server that wants a different sandbox, or its
            # own import path, is allowed to say so.
            env = {"PYTHONPATH": _package_path(), **(sandbox or {}), **env}
            servers[name] = StdioServerConfig(
                command=m.command,
                args=m.args,
                env=env or None,
                cwd=str((root / name).resolve()),
            )
        else:
            headers = {
                key: (resolve_env_ref(val, field=f"mcp[{name}].headers.{key}") if val.startswith("env:") else val)
                for key, val in m.headers.items()
            }
            servers[name] = StreamableHttpServerConfig(
                url=m.url,
                headers=headers or None,
                timeout=m.call_timeout_s,
            )
    return MCPConfig.model_validate({"mcpServers": servers})
