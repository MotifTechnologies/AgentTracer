"""MCP/ directory auto-discovery.

Every subdirectory of the discovery dir holding an ``mcp.json`` manifest is an
MCP server. All discovered servers are registered by default (default all);
YAML ``mcp.include`` / ``mcp.exclude`` narrows the set. A missing or invalid
manifest aborts the run — a silently absent tool would corrupt the generated
dataset's tool distribution (fail-fast, same policy as api_key/reasoning_key).
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import tempfile
from functools import cache
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
    #: committed to a manifest is a key published with the repository. A value
    #: that is not an `env:` reference is sent as written — right for `Accept`,
    #: and the reason the discipline is a rule for the author rather than a
    #: check here.
    headers: dict[str, str] = {}
    #: This server attaches to the task's sandbox and so needs whatever
    #: `environment.options` holds for that — which is where a backend's
    #: credentials live. Opt-in, so a key does not go to a server that only
    #: computes, or to a third-party one dropped into the directory later.
    sandbox_options: bool = False
    #: Binaries this server needs *inside the task's sandbox*. soffice hands
    #: its commands to `SandboxAccess.exec`, so a sandbox without the binary
    #: fails only at the runtime tool call — the trajectory ends normally with
    #: the tool quietly broken. Declared here, the orchestrator probes the
    #: sandbox as soon as it is up and refuses the task instead. Not for a
    #: server that only parses bytes in its own process (pdf, xlsx): their
    #: dependencies are the server's, not the sandbox's.
    requires_binaries: list[str] = []
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
        # The key itself, not its contents: the schema forbids `headers` on
        # stdio whether or not it holds anything, and a manifest that declares
        # an empty one was accepted here while failing its own validation.
        if self.transport == "stdio" and "headers" in self.model_fields_set:
            raise ValueError("'headers' applies to http transport only")
        # An http server's lifecycle is external — there is no sandbox for it
        # to reach, so a requirement on the sandbox's contents is a mistake in
        # the manifest, not a no-op. Same key-not-contents rule as `headers`.
        if self.transport == "http" and "requires_binaries" in self.model_fields_set:
            raise ValueError("'requires_binaries' applies to stdio transport only")
        # Plain names only: these are interpolated into the probe command the
        # orchestrator runs in the sandbox, and a name is not a place for shell.
        for binary in self.requires_binaries:
            if not re.fullmatch(r"[A-Za-z0-9._+-]+", binary):
                raise ValueError(
                    f"requires_binaries: {binary!r} is not a plain binary name"
                )
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
            manifest = MCPManifest.model_validate(
                json.loads(manifest_path.read_text("utf-8"))
            )
        except (ValidationError, json.JSONDecodeError) as e:
            raise ConfigError(f"mcp: invalid manifest {manifest_path}:\n{e}") from e
        if manifest.name != child.name:
            raise ConfigError(
                f"mcp: manifest name {manifest.name!r} does not match directory {child.name!r}"
            )
        manifests[manifest.name] = manifest

    selected = _select(manifests, config)

    # Resolve env: references now so a missing secret aborts before any task
    # runs. `headers` belongs here for exactly the same reason `env` does: it
    # was resolved only in the per-task rebuild, where an unresolvable secret
    # came back as one swallowed task error, retried and repeated for the whole
    # dataset, instead of a run that refuses to start.
    for manifest in selected.values():
        for field, values in (("env", manifest.env), ("headers", manifest.headers)):
            for key, value in values.items():
                if value.startswith("env:"):
                    resolve_env_ref(value, field=f"mcp[{manifest.name}].{field}.{key}")
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
#:
#: With one exception: OPTIONS carries `environment.options`, which is where a
#: backend's credentials go, and only a manifest declaring `sandbox_options`
#: receives it.
SANDBOX_ENV_PREFIX = "AGENT_TRACER_"

SANDBOX_ENV_VARS = (
    "AGENT_TRACER_ENV_TYPE",  # environment.type the sandbox was created under
    "AGENT_TRACER_SANDBOX_ID",  # what environments.attach() takes; absent for local
    "AGENT_TRACER_WORKDIR",  # the agent's working directory, inside the sandbox
    "AGENT_TRACER_HOST_DIR",  # host path the sandbox mounts, where it mounts one
    "AGENT_TRACER_USER",  # in-sandbox user, where the backend has one
    "AGENT_TRACER_OPTIONS",  # JSON: backend extras, passed to attach() untouched
)

#: The one that is not everyone's.
SANDBOX_OPTIONS_VAR = "AGENT_TRACER_OPTIONS"


@cache
def _package_path() -> str:
    """A directory holding `agent_tracer` and nothing else.

    A server that works on the agent's files calls `environments.attach()`
    rather than branching on backend, so it has to import this package — and it
    runs under its own `uv run`, which does not inherit the runner's
    interpreter. Passing the path is what lets a server stay declared with only
    the dependencies it uses itself.

    Which is exactly what the package's own parent directory takes away. `uv
    run` inherits PYTHONPATH and places it ahead of the venv it builds for the
    script, so every name in that directory shadows the server's copy. In a
    checkout it is `src/`, which holds nothing else; installed as a wheel it is
    site-packages, and the runner's `mcp>=1.2,<2` hides the `mcp>=2.0,<3` every
    server declares — `from mcp.server import MCPServer` fails across the whole
    tool set, with pydantic, httpx and anyio quietly downgraded beside it.

    So the directory that gets injected is one of ours, with a single link in
    it. Made once per run, and removed when the runner exits — the servers it
    is injected into live inside that.
    """
    import agent_tracer

    package = Path(agent_tracer.__file__).resolve().parent
    link_dir = Path(tempfile.mkdtemp(prefix="agent_tracer_pythonpath_"))
    (link_dir / package.name).symlink_to(package, target_is_directory=True)
    atexit.register(shutil.rmtree, link_dir, ignore_errors=True)
    return str(link_dir)


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


def _sandbox_for(
    manifest: MCPManifest, sandbox: dict[str, str] | None
) -> dict[str, str]:
    """This task's sandbox, as much of it as this server has asked for."""
    if not sandbox:
        return {}
    if manifest.sandbox_options:
        return sandbox
    return {k: v for k, v in sandbox.items() if k != SANDBOX_OPTIONS_VAR}


def build_stirrup_mcp_config(
    manifests: dict[str, MCPManifest],
    root: Path,
    sandbox: dict[str, str] | None = None,
):
    """Map selected manifests onto stirrup's MCPConfig for its native client.

    `sandbox` is merged into every stdio server's environment — a type, an id,
    a directory — and a manifest can override any of it, because a server that
    should be pinned to one sandbox ought to be able to say so. The exception
    is `AGENT_TRACER_OPTIONS`: it carries `environment.options`, which is where
    a backend's credentials go, so only a manifest that declares
    `sandbox_options` is given it.
    """
    from agent_tracer.mcp import _mcp2_compat

    _mcp2_compat.apply()  # must precede the stirrup import below

    from stirrup.tools.mcp import (
        MCPConfig,
        StdioServerConfig,
        StreamableHttpServerConfig,
    )

    servers: dict[str, Any] = {}
    for name, m in manifests.items():
        if m.transport == "stdio":
            env = {
                var: (
                    resolve_env_ref(val, field=f"mcp[{name}].env.{var}")
                    if val.startswith("env:")
                    else val
                )
                for var, val in m.env.items()
            }
            # Manifest last: a server that wants a different sandbox is allowed
            # to say so.
            env = {**_sandbox_for(m, sandbox), **env}
            # PYTHONPATH is the exception, because it is not the manifest's to
            # take away: it is what lets a spawned server import the package
            # that spawned it, and `environments.from_env()` is the first line
            # of every sandbox-bound server. Prepended, so a server can still
            # add its own.
            declared = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                f"{_package_path()}{os.pathsep}{declared}"
                if declared
                else _package_path()
            )
            # MCPManifest's validator refuses a stdio manifest without a
            # command; narrowed here because `transport` does not narrow it.
            if m.command is None:  # pragma: no cover
                raise ConfigError(f"mcp[{name}]: stdio server has no command")
            servers[name] = StdioServerConfig(
                command=m.command,
                args=m.args,
                env=env or None,
                cwd=str((root / name).resolve()),
            )
        else:
            headers = {
                key: (
                    resolve_env_ref(val, field=f"mcp[{name}].headers.{key}")
                    if val.startswith("env:")
                    else val
                )
                for key, val in m.headers.items()
            }
            # Same for an http manifest without a url.
            if m.url is None:  # pragma: no cover
                raise ConfigError(f"mcp[{name}]: http server has no url")
            servers[name] = StreamableHttpServerConfig(
                url=m.url,
                headers=headers or None,
                timeout=m.call_timeout_s,
            )
    return MCPConfig.model_validate({"mcpServers": servers})
