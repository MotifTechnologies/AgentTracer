"""Native FC fixture loop; no default system, submit, code_exec or summarizer."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from time import perf_counter

from stirrup import ToolMessage, UserMessage

from agent_tracer.datasets.bfcl_fixture import (
    Fixture,
    FixtureBackend,
    digest,
    grade_turn,
)
from agent_tracer.models.client import ReasoningKeyChatClient
from agent_tracer.recording.recorder import TrajectoryRecorder


class BFCLFixtureOrchestrator:
    def __init__(self, config):
        self.config = config

    async def run_task(self, task, trajectory, on_tokens=None):
        fixture = Fixture.model_validate(task.metadata["bfcl_fixture"])
        backend = FixtureBackend(fixture)
        model = self.config.model
        client = ReasoningKeyChatClient(
            model.model_name,
            model.max_tokens,
            context_window_tokens=model.context_window_tokens,
            base_url=model.base_url,
            api_key=model.resolved_api_key(),
            reasoning_key=model.reasoning_key,
            send_max_tokens=model.send_max_tokens,
            reasoning_effort=model.reasoning_effort,
            timeout=model.timeout,
            max_retries=model.max_retries,
            kwargs=model.extra_kwargs,
        )
        recorder = TrajectoryRecorder(trajectory, "a0", on_tokens)
        tools = [t.schema_ for t in fixture.tools]
        messages = []
        if fixture.system_prompt is not None:
            messages.append({"role": "system", "content": fixture.system_prompt})
        trajectory.metadata.update(
            system_prompt=fixture.system_prompt,
            tools=tools,
            fixture_provenance=fixture.provenance,
            fixture_sha256=digest(fixture.model_dump(by_alias=True)),
            protocol="native-fc-no-tool-turn-end-v1",
            category=fixture.category,
        )
        journal = (
            Path(self.config.output.path)
            / "requests"
            / f"{task.task_id}.s{trajectory.sample_idx}.jsonl"
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        binding = {
            "fixture_sha256": trajectory.metadata["fixture_sha256"],
            "run_manifest_sha256": trajectory.metadata.get("run_manifest_sha256"),
            "attempt": trajectory.metadata.get("attempt", 1),
        }
        total_steps = 0
        all_ids = set()
        last_answer = None
        try:
            for turn_index, turn in enumerate(fixture.user_turns):
                messages.append({"role": "user", "content": turn.content})
                if turn_index == 0:
                    recorder.task_message(turn.content)
                else:
                    recorder.user_message(UserMessage(content=turn.content))
                calls = []
                max_parallel = 0
                seen = set()
                completed = False
                for _ in range(self.config.agent.max_turns):
                    total_steps += 1
                    request = {
                        "messages": copy.deepcopy(messages),
                        "tools": tools,
                        "turn_index": turn_index,
                        "step": total_steps,
                        **binding,
                    }
                    # Append intent before sending so interruption cannot hide an in-flight request.
                    with journal.open("a", encoding="utf-8") as out:
                        out.write(
                            json.dumps(
                                {"kind": "request", **request}, ensure_ascii=False
                            )
                            + "\n"
                        )
                        out.flush()
                    completion = await client.generate_native(messages, tools)
                    with journal.open("a", encoding="utf-8") as out:
                        out.write(
                            json.dumps(
                                {
                                    "kind": "response",
                                    "step": total_steps,
                                    **binding,
                                    "response": completion.response,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        out.flush()
                    recorder.assistant_message(
                        total_steps, self.config.agent.max_turns, completion.assistant
                    )
                    if completion.response["choices"][0].get("finish_reason") in (
                        "length",
                        "max_tokens",
                    ):
                        trajectory.add_event(
                            "fixture_rejection",
                            {"reason": "truncated_response", "turn_index": turn_index},
                        )
                        return {"submission": None, "exit_status": "truncated"}
                    messages.append(completion.history)
                    native_calls = completion.history.get("tool_calls") or []
                    if not native_calls:
                        last_answer = completion.history.get("content")
                        if not isinstance(last_answer, str) or not last_answer.strip():
                            trajectory.add_event(
                                "fixture_rejection",
                                {
                                    "reason": "empty_final_response",
                                    "turn_index": turn_index,
                                },
                            )
                        completed = True
                        break
                    max_parallel = max(max_parallel, len(native_calls))
                    for call in native_calls:
                        call_id = call["id"]
                        name = call["function"]["name"]
                        before = digest(backend.state)
                        calls.append(name)
                        success = False
                        started = perf_counter()
                        try:
                            if not call_id or call_id in all_ids:
                                raise ValueError("duplicate_or_empty_call_id")
                            all_ids.add(call_id)
                            arguments = json.loads(call["function"]["arguments"])
                            fingerprint = digest([name, arguments, before])
                            if fingerprint in seen:
                                raise ValueError("nonprogressing_repeated_call")
                            seen.add(fingerprint)
                            result = backend.execute(name, arguments)
                            success = True
                        except Exception as exc:
                            result = {"error": str(exc)}
                            trajectory.add_event(
                                "fixture_rejection",
                                {
                                    "reason": "invalid_or_repeated_tool_call",
                                    "turn_index": turn_index,
                                    "tool": name,
                                },
                            )
                        content = json.dumps(result, ensure_ascii=False)
                        messages.append(
                            {
                                "role": "tool",
                                "content": content,
                                "tool_call_id": call_id,
                            }
                        )
                        recorder.tool_result(
                            ToolMessage(
                                content=content,
                                tool_call_id=call_id,
                                name=name,
                                success=success,
                                tool_start_time=started,
                                tool_end_time=perf_counter(),
                            )
                        )
                failures = grade_turn(
                    turn, backend.state, last_answer, calls, max_parallel
                )
                if not completed:
                    failures.append("max_turns")
                trajectory.add_event(
                    "fixture_turn_grade",
                    {
                        "turn_index": turn_index,
                        "failures": failures,
                        "final_state": copy.deepcopy(backend.state),
                        "calls": calls,
                        "max_parallel": max_parallel,
                    },
                )
                if not completed:
                    return {"submission": last_answer, "exit_status": "max_turns"}
            return {"submission": last_answer, "exit_status": "completed"}
        finally:
            await client.close()
