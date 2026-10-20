"""Independent native-function-call fixtures with deterministic state oracles.

This is a synthesis adapter, not an implementation of BFCL's official scorer.
Fixture files contain hidden state/gold; only messages and schemas reach the LLM.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Registry

from agent_tracer.config.schema import ConfigError
from agent_tracer.core.task import EvalResult, Task


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Operation(Strict):
    kind: Literal["get", "query", "update", "create", "delete", "calculate"]
    collection: str = ""
    key_argument: str = "id"
    filters: dict[str, str] = Field(default_factory=dict)
    writes: dict[str, str] = Field(default_factory=dict)
    calculation: Literal["sum", "product", "affine", "days"] | None = None
    arguments: list[str] = Field(default_factory=list)
    scale: float = 1.0
    offset: float = 0.0


def check_self_contained_schema(value: Any) -> None:
    """Keep fixture schemas local, including nested reference scopes."""
    if isinstance(value, dict):
        if "$id" in value:
            raise ValueError("fixture schemas must not change reference scope with $id")
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ValueError(
                    "fixture schema references must be root-local fragments"
                )
            check_self_contained_schema(child)
    elif isinstance(value, list):
        for child in value:
            check_self_contained_schema(child)


class FixtureTool(Strict):
    schema_: dict[str, Any] = Field(alias="schema")
    operation: Operation

    @model_validator(mode="after")
    def valid_schema(self):
        function = self.schema_.get("function", {})
        name = function.get("name", "")
        if (
            self.schema_.get("type") != "function"
            or not name
            or name in {"submit", "code_exec"}
        ):
            raise ValueError("fixture must advertise only named native functions")
        check_self_contained_schema(function["parameters"])
        Draft202012Validator.check_schema(function["parameters"])
        return self


class UserTurn(Strict):
    content: str
    expected_state: dict[str, Any]
    answer_contains: list[str] = Field(default_factory=list)
    min_calls: int = 0
    max_calls: int = 20
    required_tools: list[str] = Field(default_factory=list)
    min_parallel_calls: int = 0


class Fixture(Strict):
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    category: str
    system_prompt: str | None = None
    tools: list[FixtureTool]
    initial_state: dict[str, Any]
    user_turns: list[UserTurn] = Field(min_length=1)
    provenance: dict[str, Any]

    @model_validator(mode="after")
    def unique_names(self):
        names = [t.schema_["function"]["name"] for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("duplicate native tool names")
        for turn in self.user_turns:
            if (
                not set(turn.required_tools) <= set(names)
                or turn.min_calls > turn.max_calls
            ):
                raise ValueError("invalid turn goal")
        return self


class FixtureBackend:
    """Bounded declarative operations; never evaluate teacher-supplied code."""

    def __init__(self, fixture: Fixture):
        self.state = copy.deepcopy(fixture.initial_state)
        self.tools = {t.schema_["function"]["name"]: t for t in fixture.tools}

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tools:
            raise ValueError("unknown tool")
        tool = self.tools[name]
        Draft202012Validator(
            tool.schema_["function"]["parameters"],
            format_checker=FormatChecker(),
            registry=Registry(),
        ).validate(arguments)
        op = tool.operation
        if op.kind == "calculate":
            values = [arguments[k] for k in op.arguments]
            if op.calculation == "sum":
                result = sum(values)
            elif op.calculation == "product":
                result = math.prod(values)
            elif op.calculation == "affine":
                result = values[0] * op.scale + op.offset
            elif op.calculation == "days":
                result = (
                    date.fromisoformat(values[1]) - date.fromisoformat(values[0])
                ).days
            else:
                raise ValueError("unknown calculation")
            return {"result": result}
        records = self.state[op.collection]
        if op.kind == "query":
            return [
                copy.deepcopy(row)
                for row in records.values()
                if all(
                    row.get(field) == arguments[arg]
                    for arg, field in op.filters.items()
                )
            ]
        key = str(arguments[op.key_argument])
        if op.kind == "get":
            return copy.deepcopy(records[key])
        if op.kind == "delete":
            del records[key]
            return {"deleted": key}
        if op.kind == "create":
            if key in records:
                raise ValueError("record already exists")
            records[key] = {
                field: copy.deepcopy(arguments[arg]) for arg, field in op.writes.items()
            }
        else:
            row = records[key]
            row.update(
                {
                    field: copy.deepcopy(arguments[arg])
                    for arg, field in op.writes.items()
                }
            )
        return copy.deepcopy(records[key])


def grade_turn(
    turn: UserTurn,
    state: dict[str, Any],
    answer: str | None,
    calls: list[str],
    max_parallel: int,
) -> list[str]:
    failures = []
    if state != turn.expected_state:
        failures.append("state_goal_mismatch")
    if not turn.min_calls <= len(calls) <= turn.max_calls:
        failures.append("call_count_out_of_range")
    if not set(turn.required_tools) <= set(calls):
        failures.append("required_tool_missing")
    if max_parallel < turn.min_parallel_calls:
        failures.append("parallel_batch_missing")
    if any(
        value.casefold() not in (answer or "").casefold()
        for value in turn.answer_contains
    ):
        failures.append("required_answer_fact_missing")
    return failures


class BFCLFixtureDataset:
    name = "bfcl_fixture"

    def __init__(self, path: Path):
        self.path = path

    def load(self, split: str = "test", limit: int | None = None) -> list[Task]:
        tasks = []
        seen = set()
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                fixture = Fixture.model_validate_json(line)
                if fixture.task_id in seen:
                    raise ConfigError("duplicate fixture task identity")
                seen.add(fixture.task_id)
                tasks.append(
                    Task(
                        fixture.task_id,
                        fixture.user_turns[0].content,
                        metadata={"bfcl_fixture": fixture.model_dump(by_alias=True)},
                    )
                )
                if limit is not None and len(tasks) >= limit:
                    break
        return tasks

    def evaluate(self, task: Task, submission: str | None) -> EvalResult:
        # Runner calls evaluate_trajectory instead; never fake a string verdict.
        raise ConfigError("bfcl_fixture requires trajectory/state grading")

    def evaluate_trajectory(self, task: Task, trajectory) -> EvalResult:
        checks = [
            e.data for e in trajectory.events if e.event_type == "fixture_turn_grade"
        ]
        fixture = Fixture.model_validate(task.metadata["bfcl_fixture"])
        failures = [f for check in checks for f in check["failures"]]
        failures.extend(
            e.data["reason"]
            for e in trajectory.events
            if e.event_type == "fixture_rejection"
        )
        if len(checks) != len(fixture.user_turns):
            failures.append("incomplete_user_turns")
        return EvalResult(
            correct=not failures,
            score=float(not failures),
            details={
                "failures": failures,
                "turns_graded": len(checks),
                "grader": "fixture-state-v1",
                "answer_check": "required-fact substring; manual semantic review still required",
            },
        )
