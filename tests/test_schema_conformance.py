"""Every conversation turn carries the same key set.

The consuming org schema declares all five message keys required, with null
where a turn has no use for one. Emitting only the keys a turn needs is a
schema violation on the far side — and one that only shows up at push time,
after the trajectories are already generated.
"""

from agent_tracer.export.sharegpt import trajectory_to_record

REQUIRED = {"role", "content", "tool_calls", "thinking", "tool_call_id"}


def _traj():
    return {
        "task_id": "t1",
        "sample_idx": 0,
        "metadata": {
            "system_prompt": "be an agent",
            "model": {"model_name": "m"},
            "tools": [],
            "total_tokens": {"input": 1, "reasoning": 0, "answer": 1},
        },
        "events": [
            {"event_type": "task", "data": {"content": "solve"}, "agent_id": "a"},
            {"event_type": "thinking", "data": {"content": "hmm"}, "agent_id": "a"},
            {
                "event_type": "model_response",
                "data": {
                    "content": None,
                    "tool_calls": [
                        {"tool_call_id": "c1", "name": "f", "arguments": {"x": 1}}
                    ],
                },
                "agent_id": "a",
            },
            {
                "event_type": "tool_result",
                "data": {"tool_call_id": "c1", "name": "f", "content": "ok"},
                "agent_id": "a",
            },
            {
                "event_type": "model_response",
                "data": {"content": "done", "tool_calls": []},
                "agent_id": "a",
            },
        ],
        "result": {"exit_status": "submitted", "attempt": 1, "evaluation": None},
    }


class TestMessageKeys:
    def test_every_turn_has_every_key(self):
        for message in trajectory_to_record(_traj())["conversations"]:
            assert set(message) == REQUIRED, f"{message['role']}: {sorted(message)}"

    def test_unused_keys_are_null_not_absent(self):
        conv = trajectory_to_record(_traj())["conversations"]
        system = conv[0]
        assert system["role"] == "system"
        assert system["tool_calls"] is None
        assert system["thinking"] is None
        assert system["tool_call_id"] is None

    def test_a_turn_without_tool_calls_gets_null_not_empty_list(self):
        """`[]` and `null` both validate, but null is what the schema documents
        for an absent value and keeps the column typed the same way throughout."""
        conv = trajectory_to_record(_traj())["conversations"]
        final = conv[-1]
        assert final["role"] == "assistant" and final["content"] == "done"
        assert final["tool_calls"] is None

    def test_tool_calls_still_carry_their_payload(self):
        conv = trajectory_to_record(_traj())["conversations"]
        calling = next(m for m in conv if m["role"] == "assistant" and m["tool_calls"])
        call = calling["tool_calls"][0]
        assert call["id"] == "c1" and call["type"] == "function"
        assert isinstance(call["function"]["arguments"], str)
        assert calling["thinking"] == "hmm"
