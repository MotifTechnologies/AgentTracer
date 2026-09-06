"""The isolation the sandbox spec requires, against docker-py's real API.

A MagicMock container accepts any keyword at all, which is how `pids_limit`
reached `container.update()`: docker-py's `update_container` has no `**kwargs`,
so every `type: docker` task raised TypeError inside `__aenter__` and the
runner's retry loop built and destroyed three containers for zero trajectories.
The doubles here take exactly what the installed docker-py takes.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest
import stirrup.tools.code_backends.docker as upstream
from docker.api.container import ContainerApiMixin
from docker.models.containers import RUN_HOST_CONFIG_KWARGS

from agent_tracer.environments.docker_provider import IsolatedDockerCodeExecToolProvider

#: `container.update(**kwargs)` is `update_container(id, **kwargs)` and nothing
#: else — whatever it does not name is a TypeError.
UPDATE_SIGNATURE = inspect.signature(ContainerApiMixin.update_container)


class _Container:
    short_id = "abc123"

    def __init__(self, host_config: dict[str, Any] | None = None) -> None:
        self.attrs = {"HostConfig": host_config if host_config is not None else {}}
        self.updated: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> dict[str, Any]:
        UPDATE_SIGNATURE.bind(None, "container-id", **kwargs)
        self.updated = kwargs
        return {}

    def reload(self) -> None:
        pass

    def exec_run(self, **kwargs: Any) -> Any:
        return SimpleNamespace(exit_code=0, output=(b"", b""))

    def stop(self, **kwargs: Any) -> None:
        pass

    def remove(self, **kwargs: Any) -> None:
        pass


class _Collection:
    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] = {}
        self.container = _Container()

    def run(self, image: str, **kwargs: Any) -> _Container:
        self.run_kwargs = kwargs
        self.container.attrs["HostConfig"] = {
            "PidsLimit": kwargs.get("pids_limit", 0),
            "NetworkMode": kwargs.get("network_mode", "default"),
        }
        return self.container


class _Client:
    def __init__(self) -> None:
        self.containers = _Collection()
        self.images = SimpleNamespace(get=lambda name: name)

    def close(self) -> None:
        pass


def _provider(**kwargs: Any) -> IsolatedDockerCodeExecToolProvider:
    return IsolatedDockerCodeExecToolProvider("python:3.12-slim", **kwargs)


def _started(
    provider: IsolatedDockerCodeExecToolProvider, **host_config: Any
) -> _Container:
    """The container upstream's `__aenter__` would have created, and its state."""
    provider._client = _Client()
    container = provider._client.containers.run(
        "python:3.12-slim", command="tail -f /dev/null"
    )
    container.attrs["HostConfig"] = {
        "PidsLimit": provider._client.containers.run_kwargs.get("pids_limit", 0),
        "NetworkMode": provider._client.containers.run_kwargs.get(
            "network_mode", "default"
        ),
        **host_config,
    }
    provider._container = container
    return container


class TestCreation:
    def test_pids_and_the_network_are_set_before_the_container_starts(self):
        """Not after. `update()` cannot carry either, and a container that
        starts on the default bridge has already been on it — stirrup's
        `command` overrides CMD but not ENTRYPOINT, so an image with one gets
        seconds of network before anything could disconnect it."""
        provider = _provider(pids_limit=64)
        _started(provider)

        assert provider._client.containers.run_kwargs["pids_limit"] == 64
        assert provider._client.containers.run_kwargs["network_mode"] == "none"

    def test_only_kwargs_docker_py_turns_into_a_host_config(self):
        provider = _provider(pids_limit=64)
        _started(provider)

        injected = set(provider._client.containers.run_kwargs) - {"command"}
        assert injected <= set(RUN_HOST_CONFIG_KWARGS), injected

    def test_the_rest_of_the_client_is_still_the_client(self):
        """It is wrapped, not replaced: upstream pulls images and stops
        containers through the same object."""
        provider = _provider()
        client = _Client()
        client.ping = lambda: "pong"  # type: ignore[attr-defined]
        provider._client = client

        assert provider._client.ping() == "pong"

    def test_network_isolation_can_be_disabled(self):
        provider = _provider(network_isolation=False)
        _started(provider)

        assert "network_mode" not in provider._client.containers.run_kwargs


class TestIsolation:
    def test_memory_is_capped_with_what_update_accepts(self):
        provider = _provider(mem_limit="1g", pids_limit=64)
        container = _started(provider)

        provider._apply_isolation()

        assert container.updated == {"mem_limit": "1g", "memswap_limit": "1g"}

    def test_no_memory_cap_means_no_update_call(self):
        provider = _provider(mem_limit=None, pids_limit=None, network_isolation=False)
        container = _started(provider)

        provider._apply_isolation()

        assert container.updated == {}

    def test_a_container_that_did_not_get_the_pids_cap_is_refused(self):
        """The caps are set at creation, so this is where a provider that stopped
        reaching `containers.run` — an upstream rewrite, say — is caught. Silently
        losing them is the failure this whole class exists to prevent."""
        provider = _provider(pids_limit=64)
        _started(provider, PidsLimit=0)

        with pytest.raises(RuntimeError, match="pids"):
            provider._apply_isolation()

    def test_a_container_still_on_a_network_is_refused(self):
        provider = _provider()
        _started(provider, NetworkMode="bridge")

        with pytest.raises(RuntimeError, match="network"):
            provider._apply_isolation()


class TestUpstream:
    """The caps have to reach the container upstream creates, not one of ours.

    Everything above tests this subclass against a double. This one runs
    stirrup's own `__aenter__` — the code path a `type: docker` task takes —
    with the Docker daemon replaced, and is what fails if upstream stops
    creating its container through `self._client`.
    """

    def test_stirrups_own_aenter_creates_an_isolated_container(
        self, monkeypatch, tmp_path
    ):
        client = _Client()
        monkeypatch.setattr(upstream.docker, "from_env", lambda: client)

        provider = _provider(mem_limit="1g", pids_limit=64, temp_base_dir=tmp_path)

        async def run() -> None:
            await provider.__aenter__()
            await provider.__aexit__(None, None, None)

        asyncio.run(run())

        assert client.containers.run_kwargs["pids_limit"] == 64
        assert client.containers.run_kwargs["network_mode"] == "none"
        assert client.containers.container.updated == {
            "mem_limit": "1g",
            "memswap_limit": "1g",
        }
