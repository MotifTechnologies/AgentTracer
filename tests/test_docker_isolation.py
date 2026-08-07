from unittest.mock import MagicMock

from agent_tracer.environments.docker_provider import IsolatedDockerCodeExecToolProvider


def _provider(**kwargs) -> IsolatedDockerCodeExecToolProvider:
    provider = IsolatedDockerCodeExecToolProvider("python:3.12-slim", **kwargs)
    container = MagicMock()
    container.attrs = {"NetworkSettings": {"Networks": {"bridge": {}, "custom": {}}}}
    provider._container = container
    provider._client = MagicMock()
    return provider


class TestIsolation:
    def test_limits_and_network_detach_applied(self):
        provider = _provider(mem_limit="1g", pids_limit=64)
        provider._apply_isolation()

        provider._container.update.assert_called_once_with(
            mem_limit="1g", memswap_limit="1g", pids_limit=64
        )
        detached = [c.args[0] for c in provider._client.networks.get.call_args_list]
        assert sorted(detached) == ["bridge", "custom"]
        assert provider._client.networks.get.return_value.disconnect.call_count == 2

    def test_network_isolation_can_be_disabled(self):
        provider = _provider(network_isolation=False)
        provider._apply_isolation()
        provider._client.networks.get.assert_not_called()
        provider._container.update.assert_called_once()

    def test_no_limits_no_update(self):
        provider = _provider(mem_limit=None, pids_limit=None, network_isolation=False)
        provider._apply_isolation()
        provider._container.update.assert_not_called()
