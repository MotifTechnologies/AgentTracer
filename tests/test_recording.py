import json

from stirrup import (
    AssistantMessage,
    ReasoningBlock,
    TextBlock,
    TokenUsage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from stirrup.core.models import TurnWarningMessage

from agent_tracer.core.trajectory import Trajectory
from agent_tracer.recording.recorder import TrajectoryRecorder


def _assistant(reasoning=None, text=None, tool_calls=()):
    blocks = []
    if reasoning:
        blocks.append(ReasoningBlock(content=reasoning))
    if text:
        blocks.append(TextBlock(text=text))
    blocks.extend(tool_calls)
    return AssistantMessage(
        blocks=blocks,
        token_usage=TokenUsage(input=100, answer=20, reasoning=30),
    )


class TestRecorder:
    def _recorder(self):
        trajectory = Trajectory(task_id="t1")
        seen = []
        recorder = TrajectoryRecorder(
            trajectory, agent_id="a0", on_tokens=lambda i, o: seen.append((i, o))
        )
        return trajectory, recorder, seen

    def test_assistant_message_events(self):
        trajectory, recorder, seen = self._recorder()
        tc = ToolCall.from_provider(
            provider_id="call_1", name="code_exec", arguments='{"code": "1+1"}'
        )
        recorder.assistant_message(
            1, 10, _assistant(reasoning="think", text="answer", tool_calls=[tc])
        )

        types = [e.event_type for e in trajectory.events]
        assert types == ["thinking", "model_response", "tool_call"]
        response = trajectory.events[1].data
        assert response["content"] == "answer"
        assert response["tool_calls"][0]["name"] == "code_exec"
        assert response["tool_calls"][0]["arguments"] == {"code": "1+1"}
        assert trajectory.token_totals.input == 100
        assert seen == [(100, 50)]

    def test_tool_less_turn_kept_by_default(self):
        # The BFCL orchestrator ends a user turn on a text-only answer.
        trajectory, recorder, _ = self._recorder()
        recorder.assistant_message(1, 10, _assistant(reasoning="think", text="done"))
        assert [e.event_type for e in trajectory.events] == [
            "thinking",
            "model_response",
        ]

    def test_tool_result_event(self):
        trajectory, recorder, _ = self._recorder()
        recorder.tool_result(
            ToolMessage(
                content="ok", tool_call_id="call_1", name="code_exec", success=True
            )
        )
        event = trajectory.events[0]
        assert event.event_type == "tool_result"
        assert event.data["success"] is True

    def test_turn_warning_tagged_as_injected(self):
        trajectory, recorder, _ = self._recorder()
        recorder.user_message(TurnWarningMessage(content="You have 2 turns remaining"))
        recorder.user_message(UserMessage(content="real user turn"))
        assert [e.event_type for e in trajectory.events] == [
            "injected_turn_warning",
            "user_message",
        ]


class TestTrajectory:
    def test_event_ids_sequential(self):
        trajectory = Trajectory(task_id="t")
        trajectory.add_event("a", {})
        trajectory.add_event("b", {})
        assert [e.event_id for e in trajectory.events] == ["e0001", "e0002"]

    def test_atomic_save(self, tmp_path):
        trajectory = Trajectory(task_id="x/y")
        trajectory.add_event("a", {"k": 1})
        trajectory.finish({"exit_status": "submitted"})
        path = trajectory.save(tmp_path)
        assert path.name == "x_y.traj.json"
        assert not list(tmp_path.glob("*.tmp"))
        data = json.loads(path.read_text())
        assert data["trajectory_format"] == "agent-tracer-1.0"
        assert data["result"]["exit_status"] == "submitted"
