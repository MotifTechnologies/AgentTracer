"""A model turn with no tool call is followed by the model, not by harness text.

Upstream's default answers such a turn with a "Please continue the task" user
turn that never reaches the logger, so the export showed two assistant turns
the model never saw back to back. The record has to match the request.
"""

import asyncio

from stirrup import (
    AssistantMessage,
    SystemMessage,
    TextBlock,
    TokenUsage,
    ToolCall,
    UserMessage,
)

from agent_tracer.config.schema import (
    DatasetConfig,
    ModelConfig,
    OutputConfig,
    RunConfig,
)
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.export.sharegpt import trajectory_to_record
from agent_tracer.orchestrators.single import SingleAgentOrchestrator
from agent_tracer.recording.recorder import TrajectoryRecorder


def test_tool_less_turn_is_recorded_as_the_model_saw_it(monkeypatch, tmp_path):
    requests: list[list[object]] = []

    class Client:
        model_slug = "fake"
        context_window_tokens = 100_000
        max_tokens = 100

        def __init__(self, *args, **kwargs):
            pass

        async def generate(self, messages, tools):
            requests.append(list(messages))
            usage = TokenUsage(input=1, reasoning=0, answer=1)
            if len(requests) == 1:
                return AssistantMessage(
                    blocks=[TextBlock(text="let me think")], token_usage=usage
                )
            return AssistantMessage(
                blocks=[
                    ToolCall.from_provider(
                        provider_id="c1", name="submit", arguments='{"answer":"42"}'
                    )
                ],
                token_usage=usage,
            )

        async def close(self):
            pass

    monkeypatch.setattr("agent_tracer.orchestrators.single.build_client", Client)
    config = RunConfig(
        dataset=DatasetConfig(name="custom", path=tmp_path / "unused.jsonl"),
        model=ModelConfig(
            model_name="m",
            base_url="http://x",
            api_key="not-a-real-key",
            reasoning_key="none",
        ),
        output=OutputConfig(path=tmp_path),
    )
    task = Task("t1", "what?")
    traj = Trajectory(task.task_id)
    recorder = TrajectoryRecorder(traj, agent_id="agent-0")

    result = asyncio.run(
        SingleAgentOrchestrator(config, None)._run_agent(
            task, traj, "agent-0", recorder, []
        )
    )

    assert result["exit_status"] == "submitted"
    assert len(requests) == 2
    # The second request ends on the model's own turn: nothing was inserted.
    assert [type(m) for m in requests[1]] == [
        SystemMessage,
        UserMessage,
        AssistantMessage,
    ]
    roles = [m["role"] for m in trajectory_to_record(traj.to_dict())["conversations"]]
    assert roles == ["system", "user", "assistant", "assistant", "tool"]
