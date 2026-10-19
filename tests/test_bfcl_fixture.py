import asyncio
import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError
from stirrup import AssistantMessage, TextBlock, TokenUsage, ToolCall

from agent_tracer.config.schema import (
    DatasetConfig,
    ModelConfig,
    OutputConfig,
    RunConfig,
)
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.datasets.bfcl_fixture import (
    BFCLFixtureDataset,
    Fixture,
    FixtureBackend,
    grade_turn,
)
from agent_tracer.export.sharegpt import trajectory_to_record
from agent_tracer.models.client import NativeCompletion, ReasoningKeyChatClient
from agent_tracer.orchestrators.bfcl_fixture import BFCLFixtureOrchestrator


def fixture():
    state = {"inventory": {"k1": {"quantity": 3, "status": "ready"}}}
    return Fixture.model_validate(
        {
            "task_id": "test1",
            "category": "multi_turn",
            "initial_state": state,
            "provenance": {"seed_id": "independent:test"},
            "tools": [
                {
                    "schema": {
                        "type": "function",
                        "function": {
                            "name": "inventory_set_quantity",
                            "description": "Set the quantity.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "item_id": {"type": "string"},
                                    "quantity": {"type": "integer", "minimum": 0},
                                },
                                "required": ["item_id", "quantity"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "operation": {
                        "kind": "update",
                        "collection": "inventory",
                        "key_argument": "item_id",
                        "writes": {"quantity": "quantity"},
                    },
                }
            ],
            "user_turns": [
                {
                    "content": "Set k1 quantity to5.",
                    "expected_state": {
                        "inventory": {"k1": {"quantity": 5, "status": "ready"}}
                    },
                    "min_calls": 1,
                    "required_tools": ["inventory_set_quantity"],
                    "answer_contains": ["5"],
                },
                {
                    "content": "Thanks.",
                    "expected_state": {
                        "inventory": {"k1": {"quantity": 5, "status": "ready"}}
                    },
                    "max_calls": 0,
                },
            ],
        }
    )


def test_schema_failure_does_not_mutate_state():
    b = FixtureBackend(fixture())
    with pytest.raises(ValidationError):
        b.execute("inventory_set_quantity", {"item_id": "k1", "quantity": "5"})
    assert b.state["inventory"]["k1"]["quantity"] == 3


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
@pytest.mark.parametrize(
    "reference",
    ["http://169.254.169.254/schema", "file:///private/schema.json", "other.json"],
)
def test_external_schema_references_are_rejected(keyword, reference):
    data = fixture().model_dump(by_alias=True)
    data["tools"][0]["schema"]["function"]["parameters"][keyword] = reference
    with pytest.raises(ValueError, match="root-local fragments"):
        Fixture.model_validate(data)


def test_nested_schema_ids_cannot_change_reference_scope():
    data = fixture().model_dump(by_alias=True)
    data["tools"][0]["schema"]["function"]["parameters"]["$defs"] = {
        "quantity": {"$id": "http://169.254.169.254/schema", "$ref": "#missing"}
    }
    with pytest.raises(ValueError, match="reference scope"):
        Fixture.model_validate(data)


def test_local_schema_definitions_validate_arguments():
    data = fixture().model_dump(by_alias=True)
    schema = data["tools"][0]["schema"]["function"]["parameters"]
    schema["$defs"] = {"quantity": {"type": "integer", "minimum": 0}}
    schema["properties"]["quantity"] = {"$ref": "#/$defs/quantity"}
    backend = FixtureBackend(Fixture.model_validate(data))
    backend.execute("inventory_set_quantity", {"item_id": "k1", "quantity": 5})
    assert backend.state["inventory"]["k1"]["quantity"] == 5
    with pytest.raises(ValidationError):
        backend.execute("inventory_set_quantity", {"item_id": "k1", "quantity": "5"})


@pytest.mark.parametrize(
    "reference", ["http://169.254.169.254/schema", "file:///private/schema.json"]
)
def test_validator_cannot_retrieve_external_schema_after_mutation(
    monkeypatch, reference
):
    from referencing.exceptions import Unresolvable

    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: calls.append(a))
    f = fixture()
    f.tools[0].schema_["function"]["parameters"] = {"$ref": reference}
    backend = FixtureBackend(f)
    with pytest.raises(Unresolvable):
        backend.execute("inventory_set_quantity", {"item_id": "k1", "quantity": 5})
    assert calls == []
    assert backend.state["inventory"]["k1"]["quantity"] == 3


def test_unrequested_state_change_fails_whole_goal():
    f = fixture()
    b = FixtureBackend(f)
    b.execute("inventory_set_quantity", {"item_id": "k1", "quantity": 6})
    assert "state_goal_mismatch" in grade_turn(
        f.user_turns[0], b.state, "5", ["inventory_set_quantity"], 1
    )


def test_hidden_state_and_oracle_never_reach_native_request(tmp_path, monkeypatch):
    f = fixture()
    requests = []
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "inventory_set_quantity",
                        "arguments": '{"item_id":"k1","quantity":5}',
                    },
                }
            ],
        },
        {"role": "assistant", "content": "Quantity is5."},
        {"role": "assistant", "content": "You are welcome."},
    ]

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def generate_native(self, messages, tools):
            requests.append(
                json.loads(json.dumps({"messages": messages, "tools": tools}))
            )
            h = responses.pop(0)
            blocks = [TextBlock(text=h["content"])] if h["content"] else []
            blocks.extend(
                ToolCall.from_provider(
                    provider_id=c["id"],
                    name=c["function"]["name"],
                    arguments=c["function"]["arguments"],
                )
                for c in h.get("tool_calls", [])
            )
            return NativeCompletion(
                AssistantMessage(
                    blocks=blocks,
                    token_usage=TokenUsage(input=1, reasoning=0, answer=1),
                ),
                h,
                {"choices": [{"message": h}]},
            )

        async def close(self):
            pass

    monkeypatch.setattr(
        "agent_tracer.orchestrators.bfcl_fixture.ReasoningKeyChatClient", Client
    )
    config = RunConfig(
        dataset=DatasetConfig(name="bfcl_fixture", path=tmp_path / "unused"),
        model=ModelConfig(
            model_name="m",
            base_url="http://x",
            api_key="not-a-real-key",
            reasoning_key="none",
        ),
        output=OutputConfig(path=tmp_path),
    )
    task = Task(
        f.task_id,
        f.user_turns[0].content,
        metadata={"bfcl_fixture": f.model_dump(by_alias=True)},
    )
    traj = Trajectory(task.task_id)
    result = asyncio.run(BFCLFixtureOrchestrator(config).run_task(task, traj))
    assert result["exit_status"] == "completed"
    assert len(requests) == 3
    assert requests[0]["messages"] == [
        {"role": "user", "content": f.user_turns[0].content}
    ]
    assert requests[1]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": '{"quantity": 5, "status": "ready"}',
    }
    assert requests[2]["messages"][-1]["content"] == "Thanks."
    assert all(
        "initial_state" not in json.dumps(r) and "expected_state" not in json.dumps(r)
        for r in requests
    )
    assert (
        BFCLFixtureDataset(tmp_path / "unused").evaluate_trajectory(task, traj).correct
    )
    traj.finish({**result, "evaluation": {"correct": True}})
    record = trajectory_to_record(traj.to_dict())
    assert record["extra"]["fixture_provenance"]["seed_id"] == "independent:test"
    assert record["conversations"][-1]["role"] == "assistant"


def test_native_client_preserves_reasoning_and_omits_optional_budget(monkeypatch):
    client = ReasoningKeyChatClient(
        "m",
        100,
        context_window_tokens=1000,
        base_url="http://unused",
        api_key="test",
        reasoning_key="reasoning",
        send_max_tokens=False,
    )
    captured = []
    msg = SimpleNamespace(
        content="Done",
        reasoning="Thought",
        tool_calls=[],
        model_extra={},
        model_dump=lambda **kw: {
            "content": "Done",
            "reasoning": "Thought",
            "reasoning_details": [{"type": "reasoning.text", "text": "Thought"}],
        },
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        usage=None,
        model_dump=lambda **kw: {"id": "r1"},
    )

    async def create(**kwargs):
        captured.append(kwargs)
        return response

    monkeypatch.setattr(client._client.chat.completions, "create", create)

    async def run():
        completion = await client.generate_native(
            [{"role": "user", "content": "hello"}], []
        )
        await client.close()
        return completion

    completion = asyncio.run(run())
    assert "max_completion_tokens" not in captured[0]
    assert completion.history["reasoning_details"] == [
        {"type": "reasoning.text", "text": "Thought"}
    ]
    assert completion.assistant.blocks[0].content == "Thought"


@pytest.mark.parametrize(
    "reasoning_key", ["reasoning", "reasoning_content", "thinking", "custom_reasoning"]
)
def test_native_client_replays_configured_reasoning_on_next_tool_turn(
    monkeypatch, reasoning_key
):
    from openai.types.chat import ChatCompletion

    client = ReasoningKeyChatClient(
        "m",
        100,
        context_window_tokens=1000,
        base_url="http://unused",
        api_key="not-a-real-key",
        reasoning_key=reasoning_key,
    )
    details = [{"type": "reasoning.text", "text": "Thought", "signature": "opaque"}]
    replies = [
        {
            "role": "assistant",
            "content": None,
            reasoning_key: "Thought",
            "reasoning_details": details,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "Done", reasoning_key: "Next thought"},
    ]
    captured = []

    async def create(**kwargs):
        captured.append(json.loads(json.dumps(kwargs)))
        message = replies.pop(0)
        return ChatCompletion.model_validate(
            {
                "id": "offline-response",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls"
                        if message.get("tool_calls")
                        else "stop",
                        "message": message,
                    }
                ],
            }
        )

    async def forbid_network(*args, **kwargs):
        pytest.fail("Native history regression test must not make HTTP requests")

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    monkeypatch.setattr("httpx.AsyncClient.send", forbid_network)

    async def run():
        try:
            messages = [{"role": "user", "content": "Look it up."}]
            first = await client.generate_native(messages, [])
            messages.extend(
                [first.history, {"role": "tool", "tool_call_id": "c1", "content": "5"}]
            )
            await client.generate_native(messages, [])
            return first
        finally:
            await client.close()

    first = asyncio.run(run())
    replayed = captured[1]["messages"][1]
    assert first.assistant.blocks[0].content == "Thought"
    assert replayed[reasoning_key] == "Thought"
    assert replayed["reasoning_details"] == details
    assert replayed["tool_calls"][0]["id"] == "c1"


def runner_config(tmp_path):
    from agent_tracer.config.schema import RetryConfig, RunnerConfig

    f = fixture()
    path = tmp_path / "fixture.jsonl"
    if not path.exists():
        path.write_text(f.model_dump_json(by_alias=True) + "\n")
    return RunConfig(
        dataset=DatasetConfig(name="bfcl_fixture", path=path),
        model=ModelConfig(
            model_name="m",
            base_url="http://x",
            api_key="not-a-real-key",
            reasoning_key="none",
            max_retries=0,
        ),
        runner=RunnerConfig(retry=RetryConfig(max_attempts=1)),
        output=OutputConfig(path=tmp_path / "out"),
    )


def test_fixture_runner_uses_only_fixture_tools_and_manifest(tmp_path):
    from agent_tracer.run.runner import Runner

    runner = Runner(runner_config(tmp_path))
    assert runner.manifests == {}
    assert runner._base_metadata()["orchestrator"] == "bfcl_fixture"
    assert runner.fixture_run_digest


def test_unresolved_request_blocks_resume_before_api(tmp_path):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    runner = Runner(config)
    folder = config.output.path / "requests"
    folder.mkdir()
    (folder / "test1.s0.jsonl").write_text(
        json.dumps(
            {
                "kind": "request",
                "attempt": 1,
                "step": 1,
                "run_manifest_sha256": runner.fixture_run_digest,
            }
        )
        + "\n"
    )
    with pytest.raises(ConfigError, match="unresolved API request"):
        Runner(config)


def test_changed_fixture_blocks_reusing_output(tmp_path):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    Runner(config)
    config.dataset.path.write_text(
        config.dataset.path.read_text().replace("Set k1", "Please set k1")
    )
    with pytest.raises(ConfigError, match="fixture/config changed"):
        Runner(config)


def test_completed_api_response_without_terminal_result_blocks_resume(tmp_path):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    runner = Runner(config)
    folder = config.output.path / "requests"
    folder.mkdir()
    rows = [
        {
            "kind": kind,
            "attempt": 1,
            "step": 1,
            "run_manifest_sha256": runner.fixture_run_digest,
        }
        for kind in ("request", "response")
    ]
    (folder / "test1.s0.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    with pytest.raises(ConfigError, match="without terminal sample result"):
        Runner(config)


def test_fixture_collectors_cannot_share_active_output(tmp_path, monkeypatch):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    first, second = Runner(config), Runner(config)
    entered, release = asyncio.Event(), asyncio.Event()
    invocations = []

    async def batch(self):
        invocations.append(self)
        entered.set()
        await release.wait()
        return []

    monkeypatch.setattr(Runner, "_run_batch", batch)

    async def run():
        active = asyncio.create_task(first.run())
        await entered.wait()
        try:
            with pytest.raises(ConfigError, match="reservation exists"):
                await second.run()
            assert invocations == [first]
        finally:
            release.set()
            await active
        await second.run()
        assert invocations == [first, second]

    asyncio.run(run())
    assert not (config.output.path / ".fixture-collector.lock").exists()


def test_fixture_rechecks_binding_under_lock_before_calls(tmp_path, monkeypatch):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    runner = Runner(config)
    config.dataset.path.write_text(
        config.dataset.path.read_text().replace("Set k1", "Change k1")
    )

    async def forbidden(self):
        pytest.fail("Changed input must be refused before model calls")

    monkeypatch.setattr(Runner, "_run_batch", forbidden)
    with pytest.raises(ConfigError, match="fixture/config changed"):
        asyncio.run(runner.run())
    assert not (config.output.path / ".fixture-collector.lock").exists()


def test_fixture_lock_release_on_cancel_and_preserve_stale_lock(tmp_path, monkeypatch):
    from agent_tracer.config.schema import ConfigError
    from agent_tracer.run.runner import Runner

    config = runner_config(tmp_path)
    runner = Runner(config)
    entered = asyncio.Event()

    async def batch(self):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(Runner, "_run_batch", batch)

    async def run():
        active = asyncio.create_task(runner.run())
        await entered.wait()
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active

    asyncio.run(run())
    lock = config.output.path / ".fixture-collector.lock"
    assert not lock.exists()
    lock.write_text("stale reservation: inspect rather than steal")
    with pytest.raises(ConfigError, match="reservation exists"):
        asyncio.run(runner.run())
    assert lock.read_text() == "stale reservation: inspect rather than steal"
