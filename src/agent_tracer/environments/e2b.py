"""E2B: a hosted sandbox, no daemon of our own.

stirrup ships the provider; this is the configuration around it and the two
functions that let an out-of-process tool follow the same sandbox.

`attach` goes through the E2B SDK's own `connect`, which is what it is for. The
id has to be read off the provider's private handle — upstream does not expose
it — so that line is the one to check when stirrup is upgraded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_tracer.config.schema import EnvironmentConfig


def build(config: EnvironmentConfig, *, task_id: str | None = None) -> Any:
    from stirrup.tools.code_backends.e2b import E2BCodeExecToolProvider

    metadata = dict(config.labels)
    if task_id:
        metadata["task_id"] = task_id

    sandbox_kwargs: dict[str, Any] = {"metadata": metadata}
    # E2B's own name for "start with no internet". Set at create time for the
    # same reason it is everywhere else: a sandbox that starts connected is
    # connected, briefly, and an agent's opening move is often an install.
    if config.network_isolation:
        sandbox_kwargs["allow_internet_access"] = False

    return E2BCodeExecToolProvider(
        template=config.image,
        # E2B counts a sandbox's life from creation and kills it itself, which
        # is what `ttl` means everywhere in this config.
        timeout=int(config.ttl) if config.ttl else 600,
        allowed_commands=config.allowed_commands or None,
        shell_timeout=config.shell_timeout,
        sandbox_kwargs=sandbox_kwargs,
    )


def describe(config: EnvironmentConfig, provider: Any) -> dict[str, str | None]:
    """No `host_dir`: the sandbox is remote and mounts nothing of ours."""
    sandbox = getattr(provider, "_sbx", None)
    return {
        "sandbox_id": getattr(sandbox, "sandbox_id", None) if sandbox else None,
        "workdir": config.working_dir,
        "host_dir": None,
        "user": config.user,
    }


class _E2BAccess:
    def __init__(self, sandbox_id: str, api_key: str | None):
        self._sandbox_id = sandbox_id
        self._api_key = api_key

    def exec(self, command: str, timeout_s: float = 120) -> tuple[int, str, str]:
        from e2b_code_interpreter import Sandbox

        sandbox = Sandbox.connect(self._sandbox_id, api_key=self._api_key)
        result = sandbox.commands.run(command, timeout=int(timeout_s), request_timeout=timeout_s + 30)
        return getattr(result, "exit_code", 0), result.stdout, result.stderr


def attach(sandbox_id: str, options: dict[str, str]) -> _E2BAccess:
    return _E2BAccess(sandbox_id, options.get("api_key"))
