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

from typing import Any

from anyio import to_thread
from stirrup.tools.code_backends.docker import DockerCodeExecToolProvider


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
