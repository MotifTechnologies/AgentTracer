"""The machine the runner is on. No isolation — for development only.

`identity` is None and `attach` returns access to this same machine, because
there is nothing to attach to that is not already here. A sandbox-bound MCP
server running locally is in the sandbox by definition.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_tracer.config.schema import EnvironmentConfig


def build(config: EnvironmentConfig, *, task_id: str | None = None) -> Any:
    from stirrup.tools.code_backends import LocalCodeExecToolProvider

    return LocalCodeExecToolProvider(
        shell_timeout=config.shell_timeout,
        # `None` is stirrup's "every command allowed", so dropping an explicit
        # allowlist is not a laxer default — it is no allowlist at all, on the
        # one backend where the commands run on this machine.
        allowed_commands=config.allowed_commands or None,
    )


def describe(config: EnvironmentConfig, provider: Any) -> dict[str, str | None]:
    """No id — there is nothing to attach to that is not already here.

    `working_dir` is deliberately ignored: stirrup's local provider makes its own
    temp directory and runs every command there, so that is the directory a
    relative path has to resolve against.
    """
    temp_dir = getattr(provider, "temp_dir", None)
    return {
        "sandbox_id": None,
        "workdir": str(temp_dir) if temp_dir else None,
        "host_dir": str(temp_dir) if temp_dir else None,
        "user": None,
    }


class _LocalAccess:
    def exec(self, command: str, timeout_s: float = 120) -> tuple[int, str, str]:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s + 30,
            check=False,  # the exit code is the answer, not an exception
        )
        return proc.returncode, proc.stdout, proc.stderr


def attach(sandbox_id: str, options: dict[str, str]) -> _LocalAccess:
    return _LocalAccess()
