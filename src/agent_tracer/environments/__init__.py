"""Where an agent's code runs, and how anything else reaches the same place.

Two questions, and they have different answers:

**Building.** The orchestrator needs a `CodeExecToolProvider` for a task. Which
one depends on `environment.type`. Backends ship here for local and Docker;
anything else registers itself through the ``agent_tracer.environments``
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
BUILTIN = ("local", "docker")


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


def ensure_installed(env_type: str) -> None:
    """Refuse a backend that is not there, once, before any task runs.

    The registry is asked and the answer thrown away: what matters is that it
    raises here — at config load — rather than in `build_provider` under the
    runner's per-task error handling.
    """
    _load(env_type)


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
            host alias. `environment.options` with its `env:` references
            already resolved (see `EnvironmentConfig.resolved_options`), so
            what arrives here is the credential itself. A backend that needs
            none ignores it; the runner sends it only to the servers that
            declare `sandbox_options` in their manifest.
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
    """A relative path, against the directory the agent's commands run in.

    An absolute path is returned as given. There is deliberately no containment
    check on `..`: every tool documents its path as "absolute or relative to the
    working directory", so one would stop nothing a caller cannot do by writing
    the path out in full. The sandbox is the boundary, not this function.
    """
    if not path:
        raise ValueError("path is empty — name a file, or '.' for the working directory")
    if path.startswith("~"):
        # `~` is the sandbox's home directory, which this has no way to learn.
        # Paths are shell-quoted on the way out, so it survives as a literal:
        # the read misses, and the write makes a directory named `~` that
        # nothing else ever looks in.
        raise ValueError(
            f"{path!r} starts with '~', which is not expanded here. Give an absolute "
            "path, or one relative to the working directory."
        )
    return path if path.startswith("/") else f"{workdir.rstrip('/')}/{path}"


#: A write is one shell command, so the encoded bytes ride in the argument list.
#: ARG_MAX is 2 MiB on Linux and the command carries more than the payload, so
#: this leaves generous headroom. Larger files are a job for `code_exec`.
MAX_WRITE_BYTES = 1 << 20

#: A read comes back on stdout rather than in argv, so it can afford more — but
#: not unboundedly: it is held in memory here and base64 costs a third again.
MAX_READ_BYTES = 32 << 20


def read_bytes(access: SandboxAccess, path: str, *, timeout_s: float = 60) -> bytes:
    """The file's exact bytes, out of a sandbox that only offers `exec`.

    Base64 because a shell hands back text, and a task's files are not reliably
    UTF-8 — a scanned PDF or an .xlsx is not text at all.
    """
    import base64
    import shlex

    quoted = shlex.quote(path)
    # Checked first so an oversized file fails saying so, rather than after
    # transferring most of it.
    rc, out, _ = access.exec(f"stat -c %s {quoted}", timeout_s=30)
    if rc != 0:
        raise FileNotFoundError(f"No such file in the sandbox: {path}")
    size = int(out.strip() or 0)
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"{path} is {size} bytes, larger than this reads ({MAX_READ_BYTES}). "
            "Work on it with code_exec inside the sandbox instead."
        )

    # `-w0`: GNU base64 wraps at 76 columns by default and the newlines would
    # have to be stripped back out.
    rc, out, err = access.exec(f"base64 -w0 {quoted}", timeout_s=timeout_s)
    if rc != 0:
        raise OSError(f"Could not read {path}: {(err.strip() or out.strip())[:200]}")
    return base64.b64decode(out.strip())


def write_bytes(access: SandboxAccess, path: str, data: bytes, *, timeout_s: float = 60) -> None:
    """Put exact bytes into a sandbox that only offers `exec`."""
    import base64
    import shlex

    if len(data) > MAX_WRITE_BYTES:
        raise ValueError(
            f"{len(data)} bytes is larger than this writes ({MAX_WRITE_BYTES}). "
            "Generate the file with code_exec inside the sandbox instead."
        )
    encoded = base64.b64encode(data).decode("ascii")
    parent = path.rsplit("/", 1)[0] or "/"
    script = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}"
    )
    rc, out, err = access.exec(script, timeout_s=timeout_s)
    if rc != 0:
        raise OSError(f"Could not write {path}: {(err.strip() or out.strip())[:200]}")
