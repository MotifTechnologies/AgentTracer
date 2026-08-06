"""SingleAgentOrchestrator: one stirrup agent loops on one task.

Each task run builds a fresh client, tool set, and recorder, then executes
inside its own agent session so concurrent tasks stay fully isolated
(stirrup session state is a contextvar — task-local under asyncio).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field
from stirrup import Agent, Tool, ToolResult, ToolUseCountMetadata

from agent_tracer.config.schema import RunConfig
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.models.client import ReasoningKeyChatClient
from agent_tracer.recording.recorder import TokenCallback, TrajectoryRecorder

DEFAULT_SYSTEM_PROMPT = (
    "You are an autonomous agent solving the given task. Use the available tools "
    "when needed. When you are done, call the submit tool with your final answer."
)


class SubmitParams(BaseModel):
    """Final answer submission."""

    answer: Annotated[str, Field(description="The final answer to the task.")]


async def _submit_executor(params: SubmitParams) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=params.answer, metadata=ToolUseCountMetadata(), success=True)


SUBMIT_TOOL: Tool[SubmitParams, ToolUseCountMetadata] = Tool(
    name="submit",
    description=(
        "Submit the final answer and finish the task. Call this exactly once, "
        "when the task is complete or cannot proceed further."
    ),
    parameters=SubmitParams,
    executor=_submit_executor,
)


def _build_exec_provider(config: RunConfig):
    if config.environment.type == "docker":
        from agent_tracer.environments.docker import IsolatedDockerCodeExecToolProvider

        return IsolatedDockerCodeExecToolProvider(
            source=config.environment.image,
            working_dir=config.environment.working_dir,
            env_vars=config.environment.env_vars or None,
            shell_timeout=config.environment.shell_timeout,
            network_isolation=config.environment.network_isolation,
            mem_limit=config.environment.mem_limit,
            pids_limit=config.environment.pids_limit,
        )
    from stirrup.tools.code_backends import LocalCodeExecToolProvider

    return LocalCodeExecToolProvider(shell_timeout=config.environment.shell_timeout)


class SingleAgentOrchestrator:
    def __init__(self, config: RunConfig, mcp_config: Any | None):
        self.config = config
        self.mcp_config = mcp_config

    def _build_client(self) -> ReasoningKeyChatClient:
        m = self.config.model
        return ReasoningKeyChatClient(
            m.model_name,
            m.max_tokens,
            context_window_tokens=m.context_window_tokens,
            base_url=m.base_url,
            api_key=m.resolved_api_key(),
            reasoning_effort=m.reasoning_effort,
            timeout=m.timeout,
            max_retries=m.max_retries,
            kwargs=m.extra_kwargs or None,
            reasoning_key=m.reasoning_key,
        )

    async def run_task(
        self,
        task: Task,
        trajectory: Trajectory,
        on_tokens: TokenCallback | None = None,
    ) -> dict[str, Any]:
        agent_id = self.config.agent.role or "agent-0"
        recorder = TrajectoryRecorder(trajectory, agent_id=agent_id, on_tokens=on_tokens)

        tools: list[Any] = [_build_exec_provider(self.config)]
        if self.config.tools.web:
            from stirrup.tools.web import WebToolProvider

            tools.append(WebToolProvider(brave_api_key=self.config.tools.resolved_brave_key()))
        if self.mcp_config is not None:
            from stirrup.tools.mcp import MCPToolProvider

            tools.append(MCPToolProvider(self.mcp_config))

        agent = Agent(
            self._build_client(),
            name=agent_id,
            max_turns=self.config.agent.max_turns,
            system_prompt=self.config.agent.system_prompt or DEFAULT_SYSTEM_PROMPT,
            tools=tools,
            finish_tool=SUBMIT_TOOL,
            context_summarization_cutoff=self.config.agent.context_summarization_cutoff,
            # Always disabled: injected "turns remaining" user turns are synthetic
            # harness text that must never appear in exported training data.
            turns_remaining_warning_threshold=0,
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
            trajectory.add_event("submission", {"answer": submission}, agent_id=agent_id)
        else:
            submission = None
            exit_status = "max_turns"

        return {
            "submission": submission,
            "exit_status": exit_status,
            "run_metadata_keys": sorted(run_metadata.keys()) if run_metadata else [],
        }
