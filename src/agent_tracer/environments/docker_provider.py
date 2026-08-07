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


class _ContainersWithHostConfig:
    """`client.containers`, with the HostConfig upstream does not pass."""

    def __init__(self, collection: Any, run_kwargs: dict[str, Any]) -> None:
        self._collection = collection
        self._run_kwargs = run_kwargs

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection, name)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self._collection.run(*args, **{**self._run_kwargs, **kwargs})


class _ClientWithHostConfig:
    """The Docker client, wrapped so a container is created with its caps.

    Two of them can only be set at creation. docker-py's `update_container`
    takes `[blkio_weight, cpu_*, cpuset_*, mem_limit, mem_reservation,
    memswap_limit, kernel_memory, restart_policy]` and no `**kwargs`, so
    `pids_limit` on `update()` was a TypeError rather than a limit. And a
    container that starts attached has already been attached: stirrup's
    `command` overrides CMD but not ENTRYPOINT, so an image with one gets
    seconds on the default bridge before anything could disconnect it.

    Upstream builds its own client inside `__aenter__` and offers no hook for
    either, so the client it stores is wrapped on the way in. Everything else
    — images, networks, close — is the client itself.
    """

    def __init__(self, client: Any, **run_kwargs: Any) -> None:
        self._client = client
        self._run_kwargs = run_kwargs

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    @property
    def containers(self) -> Any:
        return _ContainersWithHostConfig(self._client.containers, self._run_kwargs)


class IsolatedDockerCodeExecToolProvider(DockerCodeExecToolProvider):
    def __init__(
        self,
        *args: Any,
        network_isolation: bool = True,
        mem_limit: str | None = "2g",
        pids_limit: int | None = 256,
        **kwargs: Any,
    ) -> None:
        # Before `super().__init__`, which assigns `_client` through the
        # property below and so reads them.
        self._network_isolation = network_isolation
        self._mem_limit = mem_limit
        self._pids_limit = pids_limit
        super().__init__(*args, **kwargs)

    @property
    def _client(self) -> Any:
        return self._docker_client

    @_client.setter
    def _client(self, client: Any) -> None:
        self._docker_client = (
            None if client is None else _ClientWithHostConfig(client, **self._creation_kwargs())
        )

    def _creation_kwargs(self) -> dict[str, Any]:
        """The isolation that has to exist before the container's first process."""
        kwargs: dict[str, Any] = {}
        if self._network_isolation:
            kwargs["network_mode"] = "none"
        if self._pids_limit:
            kwargs["pids_limit"] = self._pids_limit
        return kwargs

    def _apply_isolation(self) -> None:
        """Cap memory, and refuse a container that did not get the rest.

        Runs in a worker thread. The readback is the point: `pids_limit` and
        the network are set when the container is created, and a provider that
        stopped reaching that call would otherwise run tasks in a sandbox with
        neither and say nothing.
        """
        container = self._container
        assert container is not None

        if self._mem_limit:
            # memswap == mem disables swap headroom: the cap is the cap.
            container.update(mem_limit=self._mem_limit, memswap_limit=self._mem_limit)

        container.reload()
        host_config = container.attrs.get("HostConfig") or {}
        if self._pids_limit and host_config.get("PidsLimit") != self._pids_limit:
            raise RuntimeError(
                f"container started without the pids limit "
                f"({host_config.get('PidsLimit')!r}, expected {self._pids_limit})"
            )
        if self._network_isolation and host_config.get("NetworkMode") != "none":
            raise RuntimeError(
                f"container started on network {host_config.get('NetworkMode')!r}, "
                "expected none"
            )

    async def __aenter__(self):
        tool = await super().__aenter__()
        try:
            await to_thread.run_sync(self._apply_isolation)
        except Exception:
            # Fail-fast: a sandbox that cannot be isolated must not run tasks.
            await self.__aexit__(None, None, None)
            raise
        return tool
