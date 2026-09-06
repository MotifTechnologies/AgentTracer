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


class SandboxMissingBinariesError(ConfigError):
    """A selected MCP server's binary is not in the task's sandbox.

    ``run_fatal`` says whose image is short. The config's image is shared by
    every task without one of its own, so the whole run is doomed and aborts.
    An image the task shipped breaks only that task's samples — recorded as
    that task's error, without retries, while its siblings keep running.
    """

    def __init__(self, message: str, *, run_fatal: bool):
        super().__init__(message)
        self.run_fatal = run_fatal


@runtime_checkable
class SandboxAccess(Protocol):
    """Running one command where the agent's files are. Nothing more."""

    def exec(self, command: str, timeout_s: float = 120) -> tuple[int, str, str]:
        """Run `command` in a shell and return (exit_code, stdout, stderr)."""
        ...


class _Backend(Protocol):
    def build(self, config: EnvironmentConfig, *, task_id: str | None) -> Any: ...
    def describe(
        self, config: EnvironmentConfig, provider: Any
    ) -> dict[str, str | None]: ...
    def attach(self, sandbox_id: str, options: dict[str, str]) -> SandboxAccess: ...
    # Optional: backends with no image store simply do not define it.
    def release_image(self, image: str) -> bool: ...


def _load(env_type: str) -> _Backend:
    if env_type in BUILTIN:
        from importlib import import_module

        return import_module(f"agent_tracer.environments.{env_type}")  # type: ignore[return-value]

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        if entry.name == env_type:
            return entry.load()

    available = sorted(
        {*BUILTIN, *(e.name for e in entry_points(group=ENTRY_POINT_GROUP))}
    )
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


def attach(
    env_type: str, sandbox_id: str, options: dict[str, str] | None = None
) -> SandboxAccess:
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


def release_image(env_type: str, image: str) -> bool:
    """Drop a task's image from the local store. False if the backend cannot.

    Best-effort by nature: another task may still hold the image, and the
    daemon refuses in that case. Never fatal — a run must not fail because a
    cleanup did not happen.
    """
    backend = _load(env_type)
    hook = getattr(backend, "release_image", None)
    if hook is None:
        return False
    try:
        return bool(hook(image))
    except Exception:
        return False


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
        raise ValueError(
            "path is empty — name a file, or '.' for the working directory"
        )
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


#: The encoded bytes ride in the argument list, so a write is several shell
#: commands rather than one — see `WRITE_CHUNK_BYTES`. What is left to cap here
#: is how many round trips a single call is worth; larger files are a job for
#: `code_exec`, which generates them in the sandbox and never moves them.
MAX_WRITE_BYTES = 1 << 20

#: Raw bytes per `exec`. The binding limit is not ARG_MAX (2 MiB) but
#: MAX_ARG_STRLEN, 128 KiB for a *single* argv string — and the whole script is
#: one argument to `sh -c`. base64's 4/3 expansion put the real ceiling at
#: 98,244 bytes: 64 KiB encodes to 87 KiB and leaves room for the rest of the
#: script.
WRITE_CHUNK_BYTES = 64 << 10

#: A read comes back on stdout rather than in argv, so it can afford more — but
#: not unboundedly: it is held in memory here and base64 costs a third again.
MAX_READ_BYTES = 32 << 20


#: What else lands on the same stdout as the payload. `docker exec` runs
#: `sh -lc`, a *login* shell, so `/etc/profile` and `/etc/profile.d/*` run
#: before the command does and an image that prints `mesg: ttyname failed`, an
#: MOTD or a conda banner prints it there.
_CONTAMINATED = (
    "The sandbox printed something alongside the file. A login shell runs "
    "/etc/profile first, and an MOTD or a conda banner lands on the same stdout "
    "as the payload."
)


def read_bytes(access: SandboxAccess, path: str, *, timeout_s: float = 60) -> bytes:
    """The file's exact bytes, out of a sandbox that only offers `exec`.

    Base64 because a shell hands back text, and a task's files are not reliably
    UTF-8 — a scanned PDF or an .xlsx is not text at all.

    What comes back is checked rather than trusted, twice: the encoding has to
    be nothing but base64, and the decoded length has to be the size `stat`
    already reported. Neither check is spare. `b64decode` defaults to
    `validate=False` and *discards* anything outside the alphabet silently, so a
    banner on stdout returns a file a few bytes wrong instead of an error — and
    a PDF or an .xlsx one byte wrong is a file that no longer opens.
    """
    import base64
    import binascii
    import shlex

    quoted = shlex.quote(path)
    # `wc -c` rather than `stat -c %s`: `-c` is GNU/busybox, and on a BSD or
    # macOS local backend the missing flag would be reported as a missing file.
    # Checked first so an oversized file fails saying so, rather than after
    # transferring most of it.
    rc, out, _ = access.exec(f"wc -c < {quoted}", timeout_s=30)
    if rc != 0:
        raise FileNotFoundError(f"No such file in the sandbox: {path}")
    # Strictly one number and nothing else. Picking the last field out of a
    # noisy reply would read "Last login: ... 2026" as a 2026-byte file.
    fields = out.split()
    if len(fields) != 1 or not fields[0].isdigit():
        raise OSError(
            f"Could not size {path}: {out.strip()[:200]!r} is not a byte count. {_CONTAMINATED}"
        )
    size = int(fields[0])
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"{path} is {size} bytes, larger than this reads ({MAX_READ_BYTES}). "
            "Work on it with code_exec inside the sandbox instead."
        )

    # No `-w0`, which BSD's base64 does not have: GNU wraps at 76 columns
    # without it, and unwrapping costs one `split`.
    rc, out, err = access.exec(f"base64 < {quoted}", timeout_s=timeout_s)
    if rc != 0:
        raise OSError(f"Could not read {path}: {(err.strip() or out.strip())[:200]}")

    try:
        data = base64.b64decode("".join(out.split()), validate=True)
    except binascii.Error as exc:
        raise OSError(
            f"Could not decode {path} out of the sandbox: {exc}. {_CONTAMINATED}"
        ) from exc
    if len(data) != size:
        raise OSError(
            f"Read {len(data)} bytes of {path}, which is {size} — the transfer was "
            f"truncated, or it was not only the file. {_CONTAMINATED}"
        )
    return data


def _parent(path: str) -> str:
    """The directory `path` sits in — "." when it names no directory at all.

    `path.rsplit("/", 1)[0] or "/"` answers "a.txt" for "a.txt", and `mkdir -p`
    then makes a directory of that name.
    """
    head, sep, _ = path.rpartition("/")
    return head or ("/" if sep else ".")


def write_bytes(
    access: SandboxAccess, path: str, data: bytes, *, timeout_s: float = 60
) -> None:
    """Put exact bytes into a sandbox that only offers `exec`.

    Sent in `WRITE_CHUNK_BYTES` pieces, because the encoded payload rides in the
    argument list and one argv string is capped well below ARG_MAX. Each piece
    is decoded by its own `base64 -d`, so the split is at a whole number of
    bytes and padding stays correct.

    Staged on a sibling and moved over the destination at the end. Redirecting
    onto the destination has the shell truncate it before `base64` emits a byte,
    so a full disk or a timeout killing `docker exec` partway left the agent's
    only workbook truncated while this reported that it had failed to write —
    and `write_cells` always overwrites in place.
    """
    import base64
    import os
    import shlex

    if len(data) > MAX_WRITE_BYTES:
        raise ValueError(
            f"{len(data)} bytes is larger than this writes ({MAX_WRITE_BYTES}). "
            "Generate the file with code_exec inside the sandbox instead."
        )

    staged = shlex.quote(f"{path}.agent-tracer.{os.getpid()}")
    prologue = f"mkdir -p {shlex.quote(_parent(path))} && "
    # One chunk even for no bytes at all, so an empty file is still created.
    chunks = [
        data[at : at + WRITE_CHUNK_BYTES]
        for at in range(0, len(data), WRITE_CHUNK_BYTES)
    ] or [b""]

    def run(script: str) -> None:
        rc, out, err = access.exec(script, timeout_s=timeout_s)
        if rc != 0:
            raise OSError(
                f"Could not write {path}: {(err.strip() or out.strip())[:200]}"
            )

    try:
        for index, chunk in enumerate(chunks):
            encoded = shlex.quote(base64.b64encode(chunk).decode("ascii"))
            redirect = ">" if index == 0 else ">>"
            run(
                (prologue if index == 0 else "")
                + f"printf %s {encoded} | base64 -d {redirect} {staged}"
            )
        run(f"mv -f {staged} {shlex.quote(path)}")
    except BaseException:
        # Best effort: the sandbox may be the thing that died, and the original
        # failure is the one worth reporting.
        import contextlib

        with contextlib.suppress(Exception):
            access.exec(f"rm -f {staged}", timeout_s=30)
        raise
