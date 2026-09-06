from agent_tracer.export.sharegpt import trajectory_to_record


def _traj():
    return {
        "task_id": "t1",
        "metadata": {
            "system_prompt": "be an agent",
            "model": {"model_name": "m", "reasoning_key": "reasoning"},
            "tools": [{"type": "function", "function": {"name": "submit"}}],
            "timestamp_start": "2026-08-06T10:00:00+00:00",
            "timestamp_end": "2026-08-06T10:00:30+00:00",
            "total_tokens": {"input": 100, "reasoning": 30, "answer": 20},
        },
        "events": [
            {"event_type": "task", "data": {"content": "solve it"}, "agent_id": "a0"},
            {"event_type": "thinking", "data": {"content": "hmm"}, "agent_id": "a0"},
            {
                "event_type": "model_response",
                "data": {
                    "turn": 1,
                    "content": None,
                    "tool_calls": [
                        {
                            "tool_call_id": "c1",
                            "name": "submit",
                            "arguments": {"answer": "42"},
                        }
                    ],
                },
                "agent_id": "a0",
            },
            {"event_type": "tool_call", "data": {"name": "submit"}, "agent_id": "a0"},
            {
                "event_type": "injected_turn_warning",
                "data": {"content": "You have 1 turns remaining"},
                "agent_id": "a0",
            },
            {
                "event_type": "tool_result",
                "data": {
                    "tool_call_id": "c1",
                    "name": "submit",
                    "content": "42",
                    "success": True,
                },
                "agent_id": "a0",
            },
            {"event_type": "submission", "data": {"answer": "42"}, "agent_id": "a0"},
        ],
        "result": {
            "exit_status": "submitted",
            "attempt": 1,
            "evaluation": {"correct": True, "score": 1.0, "details": None},
        },
    }


class TestShareGPTRecord:
    def test_schema_shape(self):
        record = trajectory_to_record(_traj(), split="train", category="agent")
        assert sorted(record) == [
            "category",
            "conversations",
            "extra",
            "source",
            "tools",
        ]
        assert record["source"]["provider"] is None
        assert record["source"]["synthetic"]["synth"] is True
        assert record["extra"]["usage"] == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        assert record["extra"]["steps"] == 1
        assert record["extra"]["duration_s"] == 30.0

    def test_conversation_roles_and_thinking(self):
        conv = trajectory_to_record(_traj())["conversations"]
        assert [m["role"] for m in conv] == ["system", "user", "assistant", "tool"]
        assistant = conv[2]
        assert assistant["thinking"] == "hmm"
        assert isinstance(assistant["tool_calls"][0]["function"]["arguments"], str)

    def test_injected_turns_never_exported(self):
        conv = trajectory_to_record(_traj())["conversations"]
        assert not any("turns remaining" in (m.get("content") or "") for m in conv)
