"""SingleAgentOrchestrator: one stirrup agent loops on one task.

Each task run builds a fresh client, tool set, and recorder, then executes
inside its own agent session so concurrent tasks stay fully isolated
(stirrup session state is a contextvar — task-local under asyncio).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import shlex
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import AsyncExitStack, contextmanager
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field
from stirrup import Agent, Tool, ToolResult, ToolUseCountMetadata

from agent_tracer.config.schema import ConfigError, RunConfig
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.models.client import build_client
from agent_tracer.recording.recorder import TokenCallback, TrajectoryRecorder

DEFAULT_SYSTEM_PROMPT = (
    "You are an autonomous agent solving the given task. Use the available tools "
    "when needed. When you are done, call the submit tool with your final answer."
)


class SubmitParams(BaseModel):
    """Final answer submission."""

    answer: Annotated[str, Field(description="The final answer to the task.")]


async def _submit_executor(params: SubmitParams) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(
        content=params.answer, metadata=ToolUseCountMetadata(), success=True
    )


SUBMIT_TOOL: Tool[SubmitParams, ToolUseCountMetadata] = Tool(
    name="submit",
    description=(
        "Submit the final answer and finish the task. Call this exactly once, "
        "when the task is complete or cannot proceed further."
    ),
    parameters=SubmitParams,
    executor=_submit_executor,
)


def _resolved_target(root: Path, rel_path: str) -> Path:
    target = root / rel_path
    # Reject path escapes: seed content is data, not a trusted writer.
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"attachment path escapes workspace: {rel_path!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def _materialized_attachments(task: Task) -> Iterator[Path | None]:
    """Write a task's attachments to a temp dir for upload into the exec env.

    Seeds carry their whole workspace inline so a task is reproducible from one
    JSONL line. stirrup uploads a directory preserving relative paths, so the
    agent sees the layout the task describes.

    Two keys, because a workspace is not always text:

    - ``files``:     ``{relative/path: text}``
    - ``files_b64``: ``{relative/path: base64}`` — databases, workbooks, PDFs.
      Declared separately rather than sniffed: guessing which strings are
      base64 would eventually mangle a text file that happens to decode.
    """
    attachments = task.attachments or {}
    text_files = attachments.get("files") or {}
    binary_files = attachments.get("files_b64") or {}
    if not text_files and not binary_files:
        yield None
        return

    overlap = text_files.keys() & binary_files.keys()
    if overlap:
        raise ValueError(
            f"attachment declared as both text and binary: {sorted(overlap)}"
        )

    root = Path(tempfile.mkdtemp(prefix="agent_tracer_attach_"))
    try:
        for rel_path, content in text_files.items():
            _resolved_target(root, rel_path).write_text(content, encoding="utf-8")
        for rel_path, encoded in binary_files.items():
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as e:
                raise ValueError(
                    f"attachment {rel_path!r}: invalid base64 ({e})"
                ) from e
            _resolved_target(root, rel_path).write_bytes(raw)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _describe_sandbox(env_config: Any, provider: Any) -> dict[str, str]:
    """What an out-of-process tool needs to reach this task's sandbox."""
    from agent_tracer.environments import describe
    from agent_tracer.mcp.discovery import sandbox_env

    return sandbox_env(
        env_type=env_config.type,
        # Resolved, not as written: `api_key: env:SANDBOX_API_KEY` has to reach
        # `attach()` as the key. Unresolvable already aborted at startup.
        options=env_config.resolved_options(),
        **describe(env_config, provider),
    )


class SingleAgentOrchestrator:
    def __init__(
        self,
        config: RunConfig,
        mcp_config: Any | None,
        manifests: dict[str, Any] | None = None,
        mcp_root: Any | None = None,
    ):
        self.config = config
        self.mcp_config = mcp_config
        # Kept so the config can be rebuilt per task: the sandbox description
        # differs per task and a manifest, read once at startup, cannot carry it.
        self.manifests = manifests
        self.mcp_root = mcp_root

    async def run_task(
        self,
        task: Task,
        trajectory: Trajectory,
        on_tokens: TokenCallback | None = None,
    ) -> dict[str, Any]:
        agent_id = self.config.agent.role or "agent-0"
        recorder = TrajectoryRecorder(
            trajectory, agent_id=agent_id, on_tokens=on_tokens
        )

        from agent_tracer.environments import build_provider

        # Fixed once per task, then used for both the sandbox and the sandbox
        # description: an MCP server told a different working directory than the
        # one the agent got would resolve every relative path into nothing.
        update: dict[str, Any] = {
            "working_dir": self.config.environment.task_working_dir()
        }
        task_image = (task.metadata or {}).get("docker_image")
        if task_image:
            # A task that ships its own image needs that image: its premise is a
            # prepared checkout with the right toolchain. Running it anywhere
            # else leaves the agent looking at an empty directory and reporting
            # something, so a backend with no image concept is refused here
            # rather than producing a confidently wrong trajectory.
            if self.config.environment.type == "local":
                raise ConfigError(
                    f"task {task.task_id!r} ships docker_image {task_image!r}, but "
                    "environment.type is 'local'. Use a backend that takes an image."
                )
            update["image"] = task_image
        env_config = self.config.environment.model_copy(update=update)
        exec_provider = build_provider(env_config, task_id=task.task_id)

        # The sandbox is entered here rather than by `agent.session()` with
        # everything else. An MCP server that works on the agent's files has to
        # be told which sandbox is this task's, and that identity does not exist
        # until the sandbox is up. Handed to the session together, the two start
        # in an unspecified order and there is no point at which the id can be
        # read and passed on.
        async with AsyncExitStack() as stack:
            exec_tool = await stack.enter_async_context(exec_provider)

            # The sandbox is up and the agent has not run: the one moment a
            # missing binary can be caught without costing a trajectory.
            await self._check_sandbox_binaries(env_config, exec_provider, task_image)

            tools: list[Any] = [exec_tool]
            if self.config.tools.web:
                from stirrup.tools.web import WebToolProvider

                tools.append(
                    WebToolProvider(
                        brave_api_key=self.config.tools.resolved_brave_key()
                    )
                )
            if self.mcp_config is not None:
                from agent_tracer.mcp.provider import TimeoutMCPToolProvider

                tools.append(
                    TimeoutMCPToolProvider(
                        self._task_mcp_config(exec_provider, env_config),
                        self.manifests or {},
                    )
                )

            # Uploaded through the provider rather than `session(input_files=...)`:
            # the session is handed the resolved tool, not the provider, so stirrup
            # has no exec env to upload into by the time it looks. The temp copy is
            # only needed until the bytes are in the sandbox.
            with _materialized_attachments(task) as workspace:
                if workspace is not None:
                    # dest_dir is required, not cosmetic: without it the local
                    # backend nests everything under the temp dir's generated
                    # name, so `finance/invoices.csv` lands at
                    # `agent_tracer_attach_x9f2/finance/invoices.csv` and the
                    # agent burns turns hunting for a path the task named. The
                    # backends also disagree — only the local one renames — so
                    # the layout has to be pinned here.
                    await exec_provider.upload_files(workspace, dest_dir=".")

            return await self._run_agent(task, trajectory, agent_id, recorder, tools)

    async def _check_sandbox_binaries(
        self, env_config: Any, provider: Any, task_image: str | None
    ) -> None:
        """Refuse the task when a server's `requires_binaries` is not in the sandbox.

        soffice hands its commands to `SandboxAccess.exec`, so a sandbox
        without the binary fails only at the runtime tool call — the
        trajectory ends normally with the tool quietly broken, which is the
        silent-failure class the discovery fail-fast exists to prevent.

        Per task rather than at startup, because a task that ships its own
        ``docker_image`` must be checked against that image, and the sandbox
        it becomes does not exist until now. Probed through the same
        describe/attach path the servers themselves use, so passing here also
        means the path a server will take works.
        """
        required: dict[str, list[str]] = {}
        for name, manifest in (self.manifests or {}).items():
            for binary in manifest.requires_binaries:
                required.setdefault(binary, []).append(name)
        if not required:
            return

        from agent_tracer.environments import (
            SandboxMissingBinariesError,
            attach,
            describe,
        )

        desc = describe(env_config, provider)
        access = attach(
            env_config.type, desc["sandbox_id"], env_config.resolved_options()
        )
        # One probe for the lot: names are validated to be plain (no shell) at
        # manifest load, and quoted anyway.
        probe = "; ".join(
            f"command -v {shlex.quote(b)} >/dev/null 2>&1 || echo {shlex.quote(b)}"
            for b in sorted(required)
        )
        _code, stdout, _stderr = await asyncio.to_thread(access.exec, probe, 60)
        missing = [b for b in stdout.split() if b in required]
        if missing:
            where = (
                f"image {env_config.image!r}"
                if env_config.image
                else f"the {env_config.type!r} environment"
            )
            raise SandboxMissingBinariesError(
                "sandbox is missing "
                + ", ".join(
                    f"{b!r} (required by MCP server {', '.join(sorted(required[b]))})"
                    for b in missing
                )
                + f" — {where}. Use an image that has it, or drop the server via "
                "mcp.exclude.",
                run_fatal=task_image is None,
            )

    def _task_mcp_config(self, provider: Any, env_config: Any) -> Any:
        """The MCP config for this task, told which sandbox to work on."""
        if not self.manifests or self.mcp_root is None:
            return self.mcp_config

        from agent_tracer.mcp.discovery import build_stirrup_mcp_config

        return build_stirrup_mcp_config(
            self.manifests, self.mcp_root, _describe_sandbox(env_config, provider)
        )

    async def _run_agent(
        self,
        task: Task,
        trajectory: Trajectory,
        agent_id: str,
        recorder: TrajectoryRecorder,
        tools: list[Any],
    ) -> dict[str, Any]:
        agent = Agent(
            build_client(self.config.model),
            name=agent_id,
            max_turns=self.config.agent.max_turns,
            system_prompt=self.config.agent.system_prompt or DEFAULT_SYSTEM_PROMPT,
            tools=tools,
            finish_tool=SUBMIT_TOOL,
            context_summarization_cutoff=self.config.agent.context_summarization_cutoff,
            # Always disabled: injected "turns remaining" user turns are synthetic
            # harness text that must never appear in exported training data.
            turns_remaining_warning_threshold=0,
            # Also disabled: after a turn with no tool call, upstream appends a
            # "Please continue the task" user turn without calling any logger
            # hook. The model sees it, the trajectory does not, and the export
            # shows two assistant turns the model never saw back to back.
            # Without it the model is simply called again on its own last turn,
            # which is exactly what gets recorded.
            block_successive_assistant_messages=False,
            logger=recorder,
        )

        async with agent.session() as session:
            # Record the resolved tool specs (post provider/MCP resolution) and the
            # system prompt so exporters can reconstruct training-format records.
            # The prompt must be the ASSEMBLED one (stirrup base + custom): training
            # records have to show exactly what the model saw at generation time.
            # _build_system_prompt is private but stable under the pinned stirrup.
            from stirrup.clients.utils import to_openai_tools

            trajectory.metadata["system_prompt"] = agent._build_system_prompt()
            trajectory.metadata["tools"] = to_openai_tools(agent.tools)
            finish_params, _histories, run_metadata = await session.run(task.input)

        if finish_params is not None:
            submission: str | None = finish_params.answer
            exit_status = "submitted"
            trajectory.add_event(
                "submission", {"answer": submission}, agent_id=agent_id
            )
        else:
            submission = None
            exit_status = "max_turns"

        return {
            "submission": submission,
            "exit_status": exit_status,
            "run_metadata_keys": sorted(run_metadata.keys()) if run_metadata else [],
        }
