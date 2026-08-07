"""stirrup's Docker provider, with the isolation the sandbox spec requires.

Kept out of `docker.py` so that importing the backend does not import stirrup.
`docker.py` is imported by every out-of-process MCP server that attaches to a
running container, and a server declares only the dependencies it uses itself —
stirrup belongs to the runner that spawned it, not to the server. `build` is the
only caller, and it imports this on the way past.
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
