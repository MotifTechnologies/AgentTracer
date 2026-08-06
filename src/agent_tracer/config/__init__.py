"""Config loading: YAML file + dotted CLI overrides -> validated RunConfig.

`yaml` and `dotenv` are imported inside the functions that use them, so that
importing anything under `agent_tracer.config` costs only pydantic. The MCP
servers import `agent_tracer.environments` to reach the sandbox, and that
reaches `ConfigError` through this package; they are separate `uv run` scripts
and should not have to declare the loader's dependencies to raise a typed
error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_tracer.config.schema import ConfigError, RunConfig

__all__ = ["ConfigError", "RunConfig", "load_config"]


def _set_dotted(data: dict[str, Any], dotted: str, value: str) -> None:
    keys = dotted.split(".")
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ConfigError(f"override {dotted!r}: {key!r} is not a mapping")
    import yaml

    node[keys[-1]] = yaml.safe_load(value)


def load_config(path: str | Path, overrides: list[str] | None = None) -> RunConfig:
    """Load and validate a run config. Any invalid input aborts (fail-fast)."""
    import yaml
    from dotenv import load_dotenv

    load_dotenv()

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    for item in overrides or []:
        if "=" not in item:
            raise ConfigError(f"override {item!r}: expected key.path=value")
        dotted, value = item.split("=", 1)
        _set_dotted(raw, dotted, value)

    try:
        config = RunConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config {path}:\n{e}") from e

    config.validate_startup()
    return config
