"""Hardened Docker sandbox: stirrup's Docker backend + isolation limits.

The government-project sandbox spec requires network blocking, memory/pids caps
and mount restriction on top of Docker isolation. ``docker_provider`` holds the
subclass that applies them, and ``build`` — the only thing that needs it —
imports it on the way past.

Nothing else here imports stirrup, and that is the point: this module is what an
out-of-process MCP server imports to reach a container that already exists, and
a server is spawned with only the dependencies it declares for itself. ``attach``
is ``docker exec`` against a container someone else started, which is the whole
of what such a tool needs from this backend.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_tracer.config.schema import EnvironmentConfig


def build(config: EnvironmentConfig, *, task_id: str | None = None) -> Any:
    from agent_tracer.environments.docker_provider import (
        IsolatedDockerCodeExecToolProvider,
    )

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
        # `-c`, not `-lc`: a login shell sources /etc/profile and ~/.profile,
        # and whatever they print arrives on the stdout every sandbox-bound
        # server parses — base64 payloads, NUL-separated names, JSON. One that
        # `cd`s also moves what a relative path meant. stirrup's own code_exec
        # runs `bash -c`, so this is what keeps the agent's environment and its
        # tools' the same environment.
        argv += [self._container_id, "sh", "-c", command]
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


def release_image(image: str) -> bool:
    """Remove an image from the local store. False if it is still in use."""
    import docker
    from docker.errors import APIError, ImageNotFound

    client = docker.from_env()
    try:
        client.images.remove(image)
        return True
    except ImageNotFound:
        return True
    except APIError:
        # In use by a container that has not been reaped yet, or by a
        # concurrent task. Leaving it is the correct outcome.
        return False
    finally:
        client.close()
