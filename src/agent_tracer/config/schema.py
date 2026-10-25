"""Configuration schema with fail-fast validation.

Policy: anything that would silently degrade generated trajectories aborts the
run at config-load time — an unresolvable api_key, a missing reasoning_key, or
a malformed MCP manifest is a hard error, never a warning.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigError(ValueError):
    """Raised when the configuration is invalid. Always aborts the run."""


def resolve_env_ref(value: str, *, field: str) -> str:
    """Resolve a secret-bearing config value.

    ``env:VAR_NAME`` references resolve against the environment (recommended —
    keeps keys out of config files); any other non-empty string is passed
    through as a literal key.
    """
    if not value.startswith("env:"):
        if not value:
            raise ConfigError(f"{field}: empty value — refusing to run")
        return value
    var = value[len("env:") :]
    resolved = os.environ.get(var)
    if not resolved:
        raise ConfigError(
            f"{field}: environment variable {var!r} is not set or empty. "
            "Set it in .env or the environment — refusing to run without it."
        )
    return resolved


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(StrictModel):
    model_name: str
    base_url: str
    api_key: str = Field(
        description=(
            "Required. Either an 'env:VAR_NAME' reference (recommended) or a "
            "literal key passed directly in YAML."
        )
    )
    reasoning_key: str = Field(
        description=(
            "Response field holding reasoning/thinking text (e.g. 'reasoning_content'). "
            "Required: differs per model/server; a wrong or missing key would silently "
            "drop thinking from every trajectory. Use 'none' for non-reasoning models."
        )
    )
    max_tokens: int = 32768
    send_max_tokens: bool = True
    context_window_tokens: int = 131072
    reasoning_effort: str | None = None
    timeout: float = 120.0
    max_retries: int = 2
    extra_kwargs: dict[str, Any] = Field(default_factory=dict)

    def resolved_api_key(self) -> str:
        return resolve_env_ref(self.api_key, field="model.api_key")


class MCPDiscoveryConfig(StrictModel):
    # None = the packaged server directory (agent_tracer/mcp_servers/).
    discovery_dir: Path | None = None
    include: list[str] | None = None
    exclude: list[str] | None = None

    def resolved_discovery_dir(self) -> Path:
        if self.discovery_dir is not None:
            return self.discovery_dir
        import agent_tracer

        return Path(agent_tracer.__file__).parent / "mcp_servers"

    @model_validator(mode="after")
    def _include_xor_exclude(self) -> MCPDiscoveryConfig:
        if self.include is not None and self.exclude is not None:
            raise ConfigError("mcp: 'include' and 'exclude' cannot be used together")
        return self


class EnvironmentConfig(StrictModel):
    # Not a Literal: a backend can be installed rather than merged, and the
    # registry raises with the available names if this is not one of them.
    # Built in are local and docker.
    type: str = "local"
    image: str | None = None
    working_dir: str = "/workspace"
    # A constant working directory is a constant in every trajectory: train on
    # them and the model learns `/workspace` as a fact about the world rather
    # than as one path it was told. Randomised per task, the path stays
    # something to read out of the task, not to recall.
    randomize_working_dir: bool = True
    user: str | None = None  # in-sandbox user, where the backend has one
    shell_timeout: int = 300
    env_vars: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)

    # Isolation. Defaults match the project security spec: no network, hard
    # memory/pids caps, single temp-dir mount where the backend mounts at all.
    network_isolation: bool = True
    mem_limit: str | None = "2g"
    pids_limit: int | None = 256

    # Meaning the same thing across backends, expressed differently by each:
    # a sandbox that outlives its run, and something to attribute it to.
    # Per-task images are pulled per task and never reused across tasks, so a
    # run over a few hundred of them fills the disk. Only images a task brought
    # are released; the image named in this config is shared by every task that
    # has none of its own, and re-pulling it each time would be absurd.
    release_task_images: bool = True

    ttl: float | None = None  # seconds; a backend may enforce it or label and sweep
    labels: dict[str, str] = Field(default_factory=dict)

    # Anything a specific backend needs and no other does. What `attach()`
    # takes, so this is where a backend's credentials go — see resolved_options.
    options: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Backend-specific extras passed to attach(), e.g. an API key or host alias. "
            "Values take an 'env:VAR_NAME' reference (recommended) or a literal."
        ),
    )

    # Plausible places work would live, so the varied path still reads as a
    # real one. The suffix is what makes it unlearnable.
    _WORKDIR_ROOTS = (
        "/workspace",
        "/srv/job",
        "/opt/run",
        "/data/task",
        "/home/agent/work",
    )

    def task_working_dir(self) -> str:
        """The working directory for one task — randomised unless pinned."""
        if not self.randomize_working_dir:
            return self.working_dir
        import secrets

        root = secrets.choice(self._WORKDIR_ROOTS)
        return f"{root}_{secrets.token_hex(3)}"

    def resolved_options(self) -> dict[str, str]:
        """`options` with its `env:` references resolved.

        A backend reads its credentials out of here, so these get the same
        discipline as `model.api_key` rather than being handed on untouched.
        Written as `api_key: env:SANDBOX_KEY`, the literal string used to reach
        the backend, which left a plaintext key in the YAML as the only thing
        that worked.
        """
        return {
            key: resolve_env_ref(value, field=f"environment.options.{key}")
            for key, value in self.options.items()
        }

    @model_validator(mode="after")
    def _image_is_required(self) -> EnvironmentConfig:
        # `local` runs on this machine and has nothing to pull.
        if self.type != "local" and not self.image:
            raise ConfigError(f"environment: {self.type} type requires 'image'")
        return self


class AgentConfig(StrictModel):
    role: str | None = None
    system_prompt: str | None = None
    max_turns: int = 30
    # 1.0 disables stirrup's auto-summarization: summarization rewrites history
    # mid-run, which corrupts trajectories destined for SFT.
    context_summarization_cutoff: float = 1.0


class ToolsConfig(StrictModel):
    """Built-in stirrup tools, enabled per run."""

    web: bool = False
    brave_api_key: str | None = Field(
        default=None,
        description=(
            "Brave Search key for web_search. An 'env:VAR_NAME' reference "
            "(recommended) or a literal. Falls back to $BRAVE_API_KEY."
        ),
    )

    def resolved_brave_key(self) -> str | None:
        """The key, from config or the environment. None if neither has one."""
        if self.brave_api_key is not None:
            return resolve_env_ref(self.brave_api_key, field="tools.brave_api_key")
        return os.environ.get("BRAVE_API_KEY") or None


class RetryConfig(StrictModel):
    max_attempts: int = 3
    backoff_base: float = 2.0


class RunnerConfig(StrictModel):
    max_concurrency: int = 8
    # Rollouts per task. >1 is how best-of-N / rejection-sampled SFT data is
    # made: sample repeatedly, keep what passed. Each sample is a separate
    # trajectory, checkpointed independently.
    samples_per_task: int = 1
    task_timeout: float = 1800.0
    retry: RetryConfig = Field(default_factory=RetryConfig)
    checkpoint: bool = True


class DatasetConfig(StrictModel):
    name: str = "custom"
    path: Path | None = None
    split: str = "test"
    limit: int | None = None

    @model_validator(mode="after")
    def _custom_needs_path(self) -> DatasetConfig:
        if (
            self.name in ("custom", "swebench_local", "bfcl_fixture")
            and self.path is None
        ):
            raise ConfigError(
                f"dataset: {self.name} dataset requires 'path' (JSONL file)"
            )
        return self


class OutputConfig(StrictModel):
    path: Path = Path("results")
    save_trajectories: bool = True


class RunConfig(StrictModel):
    dataset: DatasetConfig
    model: ModelConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    mcp: MCPDiscoveryConfig = Field(default_factory=MCPDiscoveryConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    def validate_startup(self) -> None:
        """Fail-fast checks that touch the environment (called once at startup)."""
        self.model.resolved_api_key()
        if not self.model.reasoning_key:
            raise ConfigError("model.reasoning_key: required — refusing to run")
        # Upstream drops web_search from the tool set when there is no key and
        # says nothing: the agent then gets web_fetch alone, every trajectory in
        # the run carries a tool set nobody asked for, and the run exits clean.
        if self.tools.web and not self.tools.resolved_brave_key():
            raise ConfigError(
                "tools.web is on but no Brave Search key was found. Set "
                "tools.brave_api_key (an 'env:VAR_NAME' reference or a literal) "
                "or BRAVE_API_KEY in the environment — without it web_search is "
                "silently dropped and only web_fetch reaches the agent. "
                "Set tools.web: false if that is what you want."
            )
        # `environment.type` is a str, so the registry is the only thing that
        # knows whether it names a backend. Left to `build_provider`, the first
        # check happens per task inside `Runner._run_one`'s `except Exception`,
        # and a typo becomes three retries and an error trajectory for every
        # task in the dataset rather than a config the run refuses to start on.
        from agent_tracer.environments import ensure_installed

        ensure_installed(self.environment.type)
        self.environment.resolved_options()
