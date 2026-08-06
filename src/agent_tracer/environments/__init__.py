"""Where an agent's code runs, and how anything else reaches the same place.

Two questions, and they have different answers:

**Building.** The orchestrator needs a `CodeExecToolProvider` for a task. Which
one depends on `environment.type`. Backends ship here for local, Docker and
E2B; anything else registers itself through the ``agent_tracer.environments``
entry point group, so a sandbox we do not distribute is installed rather than
merged.

**Attaching.** An MCP server that works on the agent's files runs in its own
process and must reach the sandbox that already exists. It cannot build one —
that would be a second, empty sandbox — so it attaches by id and gets back the
one thing it needs, which is the ability to run a command. `SandboxAccess` is
deliberately that small: a server converting a document does not need a file
API, a lifecycle, or an event loop.

Adding a backend means three functions. `build` for the orchestrator, `describe`
so a sandbox can be named and located afterwards, and `attach` so out-of-process
tools can follow it.
"""

from __future__ import annotations

import json
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agent_tracer.config.schema import ConfigError

if TYPE_CHECKING:
    from agent_tracer.config.schema import EnvironmentConfig

ENTRY_POINT_GROUP = "agent_tracer.environments"

#: Backends that ship with the package. Anything else arrives by entry point.
BUILTIN = ("local", "docker", "e2b")


@runtime_checkable
class SandboxAccess(Protocol):
    """Running one command where the agent's files are. Nothing more."""

    def exec(self, command: str, timeout_s: float = 120) -> tuple[int, str, str]:
        """Run `command` in a shell and return (exit_code, stdout, stderr)."""
        ...


class _Backend(Protocol):
    def build(self, config: EnvironmentConfig, *, task_id: str | None) -> Any: ...
    def describe(self, config: EnvironmentConfig, provider: Any) -> dict[str, str | None]: ...
    def attach(self, sandbox_id: str, options: dict[str, str]) -> SandboxAccess: ...


def _load(env_type: str) -> _Backend:
    if env_type in BUILTIN:
        from importlib import import_module

        return import_module(f"agent_tracer.environments.{env_type}")  # type: ignore[return-value]

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        if entry.name == env_type:
            return entry.load()

    available = sorted({*BUILTIN, *(e.name for e in entry_points(group=ENTRY_POINT_GROUP))})
    raise ConfigError(
        f"environment: unknown type {env_type!r} (available: {', '.join(available)}). "
        "A backend that is not built in has to be installed — it registers itself "
        f"under the {ENTRY_POINT_GROUP} entry point group."
    )


def build_provider(config: EnvironmentConfig, *, task_id: str | None = None) -> Any:
    """The `CodeExecToolProvider` this configuration asks for."""
    return _load(config.type).build(config, task_id=task_id)


def describe(config: EnvironmentConfig, provider: Any) -> dict[str, str | None]:
    """Where this running sandbox is, for something outside it.

    Keys: `sandbox_id` (what `attach` takes, None where the backend has no id),
    `workdir` (where the agent's commands actually run), `host_dir` (the host
    path it mounts, where it mounts one) and `user`.

    Asked of the backend rather than read off the config, because the two
    disagree. stirrup's local provider runs every command in a temp directory it
    makes itself and ignores `working_dir` entirely, so a server resolving a
    relative path against the configured value would look in the wrong place.
    Only the backend knows which is true for it.
    """
    return _load(config.type).describe(config, provider)


def attach(env_type: str, sandbox_id: str, options: dict[str, str] | None = None) -> SandboxAccess:
    """Reach a sandbox that already exists, from another process.

    Args:
        env_type: The `environment.type` the sandbox was created under.
        sandbox_id: The `sandbox_id` that `describe` reported for it.
        options: Backend-specific extras — the in-sandbox user, an API key, a
            host alias. Passed through untouched; a backend that needs none
            ignores it.
    """
    return _load(env_type).attach(sandbox_id, options or {})


def from_env(environ: dict[str, str] | None = None) -> tuple[SandboxAccess, str]:
    """Attach to the sandbox described in the environment.

    The counterpart to `mcp.discovery.sandbox_env`: the runner writes the
    description onto every server it spawns, and a server that works on the
    agent's files reads it back here. Returns the access and the directory a
    relative path should resolve against, which is every sandbox-bound server's
    first two lines.

    Defaults to `local` with the process's own cwd, so a server can be run by
    hand — that is what its smoke test does.
    """
    import os

    env = os.environ if environ is None else environ
    options = json.loads(env.get("AGENT_TRACER_OPTIONS") or "{}")
    access = attach(
        env.get("AGENT_TRACER_ENV_TYPE", "local"),
        env.get("AGENT_TRACER_SANDBOX_ID", ""),
        options,
    )
    return access, env.get("AGENT_TRACER_WORKDIR") or os.getcwd()


def resolve(path: str, workdir: str) -> str:
    """A relative path, against the directory the agent's commands run in."""
    return path if path.startswith("/") else f"{workdir.rstrip('/')}/{path}"
