"""A tool-less turn the loop answers with "Please continue" is left out.

Upstream answers a model turn with no tool call by appending a "Please
continue the task" user turn that never reaches the logger. Recording the
tool-less turn alone made the export show two assistant turns back to back,
so both are left out and the record picks up at the next turn.
"""

import asyncio

from stirrup import (
    AssistantMessage,
    ReasoningBlock,
    TextBlock,
    TokenUsage,
    ToolCall,
    UserMessage,
)

from agent_tracer.config.schema import (
    AgentConfig,
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

USAGE = TokenUsage(input=1, reasoning=0, answer=1)


def _text(text, reasoning=None):
    blocks = [ReasoningBlock(content=reasoning)] if reasoning else []
    return AssistantMessage(blocks=[*blocks, TextBlock(text=text)], token_usage=USAGE)


def _submit():
    return AssistantMessage(
        blocks=[
            ToolCall.from_provider(
                provider_id="c1", name="submit", arguments='{"answer":"42"}'
            )
        ],
        token_usage=USAGE,
    )


def _run(monkeypatch, tmp_path, responses, max_turns):
    requests: list[list[object]] = []

    class Client:
        model_slug = "fake"
        context_window_tokens = 100_000
        max_tokens = 100

        def __init__(self, *args, **kwargs):
            pass

        async def generate(self, messages, tools):
            requests.append(list(messages))
            return responses.pop(0)

        async def close(self):
            pass

    monkeypatch.setattr("agent_tracer.orchestrators.single.build_client", Client)
    # Upstream caches a run that ends without submit under ~/.cache/stirrup.
    monkeypatch.setattr("stirrup.core.cache.DEFAULT_CACHE_DIR", tmp_path / "cache")
    config = RunConfig(
        dataset=DatasetConfig(name="custom", path=tmp_path / "unused.jsonl"),
        model=ModelConfig(
            model_name="m",
            base_url="http://x",
            api_key="not-a-real-key",
            reasoning_key="none",
        ),
        agent=AgentConfig(max_turns=max_turns),
        output=OutputConfig(path=tmp_path),
    )
    task = Task("t1", "what?")
    traj = Trajectory(task.task_id)
    recorder = TrajectoryRecorder(traj, agent_id="agent-0", skip_continued_turns=True)
    result = asyncio.run(
        SingleAgentOrchestrator(config, None)._run_agent(
            task, traj, "agent-0", recorder, []
        )
    )
    return result, traj, requests


def test_continued_turn_and_its_nudge_are_left_out(monkeypatch, tmp_path):
    result, traj, requests = _run(
        monkeypatch,
        tmp_path,
        [_text("let me think", reasoning="hmm"), _submit()],
        max_turns=5,
    )

    assert result["exit_status"] == "submitted"
    # What the skip relies on: upstream still nudges after a tool-less turn.
    nudge = requests[1][-1]
    assert isinstance(nudge, UserMessage)
    assert nudge.content == "Please continue the task"

    conversation = trajectory_to_record(traj.to_dict())["conversations"]
    assert [m["role"] for m in conversation] == ["system", "user", "assistant", "tool"]
    assistant = conversation[2]
    assert assistant["tool_calls"][0]["function"]["name"] == "submit"
    # The skipped turn's reasoning must not attach to the next turn.
    assert assistant["thinking"] is None
    # Its tokens were still spent.
    assert traj.token_totals.answer == 2


def test_tool_less_last_turn_is_kept(monkeypatch, tmp_path):
    result, traj, _ = _run(
        monkeypatch, tmp_path, [_text("first"), _text("last")], max_turns=2
    )

    assert result["exit_status"] == "max_turns"
    conversation = trajectory_to_record(traj.to_dict())["conversations"]
    assert [m["role"] for m in conversation] == ["system", "user", "assistant"]
    assert conversation[2]["content"] == "last"
