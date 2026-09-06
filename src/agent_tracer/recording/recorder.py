"""TrajectoryRecorder: a silent stirrup logger that records events.

Implements stirrup's AgentLoggerBase but prints nothing — console output is
owned by the runner's progress display (bar / TPS / ETA), not by per-agent
logs. Every hook appends a structured event to the task's Trajectory; token
deltas are additionally forwarded to an optional callback so the runner can
aggregate throughput across concurrent tasks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from stirrup import (
    AssistantMessage,
    ReasoningBlock,
    TextBlock,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from stirrup.utils.logging import AgentLoggerBase

from agent_tracer.core.trajectory import Trajectory

TokenCallback = Callable[[int, int], None]  # (input_tokens, output_tokens)


def _parse_arguments(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return arguments


class TrajectoryRecorder(AgentLoggerBase):
    def __init__(
        self,
        trajectory: Trajectory,
        agent_id: str,
        on_tokens: TokenCallback | None = None,
    ) -> None:
        self.trajectory = trajectory
        self.agent_id = agent_id
        self.on_tokens = on_tokens
        # Properties stirrup sets after construction
        self.name = agent_id
        self.model: str | None = None
        self.max_turns: int | None = None
        self.depth = 0
        self.finish_params = None
        self.run_metadata: dict[str, list[Any]] | None = None
        self.output_dir: str | None = None

    # -- context manager (no live display to manage) --------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def pause_live(self) -> None:
        return None

    def resume_live(self) -> None:
        return None

    # -- recording hooks -------------------------------------------------------

    def task_message(self, task: str | list[Any]) -> None:
        self.trajectory.add_event(
            "task",
            {"content": task if isinstance(task, str) else [str(t) for t in task]},
            agent_id=self.agent_id,
        )

    def user_message(self, user_message: UserMessage) -> None:
        # Harness-injected turns (turn warnings, summaries) are tagged with their
        # own event types so exporters never mistake them for real user turns.
        kind = getattr(user_message, "kind", "user")
        event_type = "user_message" if kind == "user" else f"injected_{kind}"
        self.trajectory.add_event(
            event_type,
            {"content": user_message.content},
            agent_id=self.agent_id,
        )

    def assistant_message(
        self,
        turn: int,
        max_turns: int,
        assistant_message: AssistantMessage,
    ) -> None:
        usage = assistant_message.token_usage
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in assistant_message.blocks:
            if isinstance(block, ReasoningBlock):
                self.trajectory.add_event(
                    "thinking", {"content": block.content}, agent_id=self.agent_id
                )
            elif isinstance(block, TextBlock):
                content_parts.append(block.text)
            elif isinstance(block, ToolCall):
                tool_calls.append(
                    {
                        "tool_call_id": block.tool_call_id,
                        "name": block.name,
                        "arguments": _parse_arguments(block.arguments),
                    }
                )

        self.trajectory.add_event(
            "model_response",
            {
                "turn": turn,
                "content": "\n".join(content_parts) or None,
                "tool_calls": tool_calls,
                "usage": {
                    "input": usage.input,
                    "reasoning": usage.reasoning,
                    "answer": usage.answer,
                },
                "duration_s": (
                    round(
                        assistant_message.request_end_time
                        - assistant_message.request_start_time,
                        3,
                    )
                    if assistant_message.request_end_time
                    and assistant_message.request_start_time
                    else None
                ),
            },
            agent_id=self.agent_id,
        )
        for tc in tool_calls:
            self.trajectory.add_event("tool_call", tc, agent_id=self.agent_id)

        self.trajectory.token_totals.add(usage.input, usage.reasoning, usage.answer)
        if self.on_tokens:
            self.on_tokens(usage.input, usage.reasoning + usage.answer)

    def tool_result(self, tool_message: ToolMessage) -> None:
        duration = None
        if tool_message.tool_end_time and tool_message.tool_start_time:
            duration = round(
                tool_message.tool_end_time - tool_message.tool_start_time, 3
            )
        self.trajectory.add_event(
            "tool_result",
            {
                "tool_call_id": tool_message.tool_call_id,
                "name": tool_message.name,
                "success": tool_message.success,
                "content": tool_message.content,
                "duration_s": duration,
            },
            agent_id=self.agent_id,
        )

    def on_step(
        self,
        step: int,
        tool_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        return None

    def context_summarization_start(self, pct_used: float, cutoff: float) -> None:
        self.trajectory.add_event(
            "context_summarization_start",
            {"pct_used": pct_used, "cutoff": cutoff},
            agent_id=self.agent_id,
        )

    def context_summarization_complete(self, summary: str, bridge: str) -> None:
        self.trajectory.add_event(
            "context_summarization_complete",
            {"summary": summary, "bridge": bridge},
            agent_id=self.agent_id,
        )

    # -- plain log levels: recorded only for errors, never printed -------------

    def debug(self, message: str, *args: object) -> None:
        return None

    def info(self, message: str, *args: object) -> None:
        return None

    def warning(self, message: str, *args: object) -> None:
        self.trajectory.add_event(
            "warning",
            {"message": message % args if args else message},
            agent_id=self.agent_id,
        )

    def error(self, message: str, *args: object) -> None:
        self.trajectory.add_event(
            "error",
            {"message": message % args if args else message},
            agent_id=self.agent_id,
        )
