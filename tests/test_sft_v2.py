"""Offline SFT termination augmentation preserves answers and tool history."""

import copy
import json
import runpy
from pathlib import Path

import pytest

builder = runpy.run_path(str(Path(__file__).parents[1] / "scripts/build_sft_v2.py"))


def record():
    return {
        "conversations": [
            {
                "role": "system",
                "content": "You will need to call a finish tool as your last step, where you will pass your finish reason and any required final fields for that tool. When you are done, call the submit tool with your final answer.",
            },
            {
                "role": "user",
                "content": "Submit only the answer, with no explanation.\n\n## Issue\nBefore you submit your issue, check this.",
            },
            {
                "role": "assistant",
                "thinking": "Inspect first",
                "tool_calls": [
                    {
                        "id": "read",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "read", "content": "42"},
            {
                "role": "assistant",
                "thinking": "Submit now",
                "content": "irrelevant preamble",
                "tool_calls": [
                    {
                        "id": "end",
                        "type": "function",
                        "function": {
                            "name": "submit",
                            "arguments": '{"answer":"42\\n"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "end", "content": "Done"},
        ],
        "tools": [
            {"type": "function", "function": {"name": name}}
            for name in ("read_file", "submit")
        ],
        "source": {"subset": "test"},
        "extra": {"evaluation": {"correct": True}},
    }


def test_preserves_source_history_and_exact_answer():
    original = record()
    snapshot = copy.deepcopy(original)
    result = builder["plain_answer"](original)
    assert original == snapshot
    assert result["conversations"][2:4] == original["conversations"][2:4]
    assert result["conversations"][-1] == {
        "role": "assistant",
        "content": "42\n",
        "tool_calls": None,
        "thinking": None,
        "tool_call_id": None,
    }
    assert result["tools"] == original["tools"][:1]
    assert result["conversations"][1]["content"].startswith("Return only")
    assert result["conversations"][1]["content"].endswith(
        "Before you submit your issue, check this."
    )
    samples = list(builder["turn_split"](result))
    assert samples[-1]["messages"][-1]["reasoning_content"] is None
    assert samples[0]["messages"][-1]["reasoning_content"] == "Inspect first"
    assert samples[-1]["messages"][2]["reasoning_content"] is None


@pytest.mark.parametrize(
    "defect",
    ["mismatched_id", "extra_call", "empty_answer", "unknown_system", "missing_schema"],
)
def test_rejects_unsafe_conversion(defect):
    value = record()
    if defect == "mismatched_id":
        value["conversations"][-1]["tool_call_id"] = "wrong"
    elif defect == "extra_call":
        value["conversations"][-2]["tool_calls"].append(
            value["conversations"][2]["tool_calls"][0]
        )
    elif defect == "empty_answer":
        value["conversations"][-2]["tool_calls"][0]["function"]["arguments"] = (
            '{"answer":""}'
        )
    elif defect == "unknown_system":
        value["conversations"][0]["content"] = "Call finish at the end."
    else:
        value["tools"] = value["tools"][:1]
    with pytest.raises(ValueError):
        builder["plain_answer"](value)


def test_build_reproducible_and_does_not_overwrite(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(record()) + "\n")
    a, b = tmp_path / "a", tmp_path / "b"
    manifest = builder["build"](source, a)
    builder["build"](source, b)
    assert manifest["trajectories"] == 2
    assert manifest["turnsplit_samples"] == 4
    assert manifest["mix"] == {"submit": 1, "plain": 1}
    for name in manifest["files"]:
        assert (a / name).read_bytes() == (b / name).read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        builder["build"](source, a)


@pytest.mark.parametrize("arguments", ["null", "[]", "42", '"answer"', None, []])
def test_invalid_submit_arguments_report_source_row_before_writing(tmp_path, arguments):
    invalid = record()
    invalid["conversations"][-2]["tool_calls"][0]["function"]["arguments"] = arguments
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(record()) + "\n" + json.dumps(invalid) + "\n")
    output = tmp_path / "output"

    with pytest.raises(
        ValueError, match="Source row 1: submit arguments must be an object"
    ):
        builder["build"](source, output)

    assert not output.exists()
