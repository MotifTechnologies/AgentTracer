"""Hardened Docker sandbox: stirrup's Docker backend + isolation limits.

The government-project sandbox spec requires network blocking, memory/pids
caps, and mount restriction on top of Docker isolation. stirrup 0.2.0's
``DockerCodeExecToolProvider`` gives the container lifecycle, the single
temp-dir volume mount, and per-command wall-clock timeouts, but passes no
``network_mode``/``mem_limit`` to ``containers.run``.

Rather than copying the provider's ``__aenter__``, this subclass applies the
limits immediately after the container starts and *before any agent code can
execute*: the container idles on ``tail -f /dev/null`` until the first
``code_exec`` call, so post-start ``container.update()`` + network disconnect
closes the gap without forking upstream code.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from stirrup.tools.code_backends.docker import DockerCodeExecToolProvider

if TYPE_CHECKING:
    from agent_tracer.config.schema import EnvironmentConfig


class IsolatedDockerCodeExecToolProvider(DockerCodeExecToolProvider):
    def __init__(
        self,
        *args: Any,
        network_isolation: bool = True,
        mem_limit: str | None = "2g",
        pids_limit: int | None = 256,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._network_isolation = network_isolation
        self._mem_limit = mem_limit
        self._pids_limit = pids_limit

    def _apply_isolation(self) -> None:
        """Apply resource caps and detach networks (runs in a worker thread)."""
        container = self._container
        assert container is not None and self._client is not None

        update_kwargs: dict[str, Any] = {}
        if self._mem_limit:
            # memswap == mem disables swap headroom: the cap is the cap.
            update_kwargs["mem_limit"] = self._mem_limit
            update_kwargs["memswap_limit"] = self._mem_limit
        if self._pids_limit:
            update_kwargs["pids_limit"] = self._pids_limit
        if update_kwargs:
            container.update(**update_kwargs)

        if self._network_isolation:
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
            for name in networks:
                self._client.networks.get(name).disconnect(container)

    async def __aenter__(self):
        tool = await super().__aenter__()
        try:
            await to_thread.run_sync(self._apply_isolation)
        except Exception:
            # Fail-fast: a sandbox that cannot be isolated must not run tasks.
            await self.__aexit__(None, None, None)
            raise
        return tool


def build(config: EnvironmentConfig, *, task_id: str | None = None) -> Any:
    # `labels` and `ttl` are not passed on: upstream's provider takes neither,
    # and a daemon on this machine is not the shared, outlives-the-run host that
    # made them worth having. They stay in the config for the backends where
    # they mean something.
    return IsolatedDockerCodeExecToolProvider(
        source=config.image,
        working_dir=config.working_dir,
        env_vars=config.env_vars or None,
        shell_timeout=config.shell_timeout,
        allowed_commands=config.allowed_commands or None,
        network_isolation=config.network_isolation,
        mem_limit=config.mem_limit,
        pids_limit=config.pids_limit,
    )


def describe(config: EnvironmentConfig, provider: Any) -> dict[str, str | None]:
    temp_dir = getattr(provider, "temp_dir", None)
    return {
        "sandbox_id": provider.container_id,
        "workdir": config.working_dir,
        "host_dir": str(temp_dir) if temp_dir else None,
        "user": config.user,
    }


class _DockerAccess:
    """`docker exec` against a container someone else started."""

    def __init__(self, container_id: str, user: str | None):
        self._container_id = container_id
        self._user = user

    def exec(self, command: str, timeout_s: float = 120) -> tuple[int, str, str]:
        argv = ["docker", "exec"]
        if self._user:
            argv += ["--user", self._user]
        argv += [self._container_id, "sh", "-lc", command]
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s + 30,
            check=False,  # the exit code is the answer, not an exception
        )
        return proc.returncode, proc.stdout, proc.stderr


def attach(sandbox_id: str, options: dict[str, str]) -> _DockerAccess:
    return _DockerAccess(sandbox_id, options.get("user"))
