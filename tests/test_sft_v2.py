"""Offline SFT termination augmentation preserves answers and tool history."""

import copy
import io
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


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_jsonl_preserves_unicode_separators_inside_strings(tmp_path, line_ending):
    value = record()
    answer = "first\u2028second\u2029third"
    value["conversations"][-2]["tool_calls"][0]["function"]["arguments"] = json.dumps(
        {"answer": answer}, ensure_ascii=False
    )
    source = tmp_path / "input.jsonl"
    row = json.dumps(value, ensure_ascii=False)
    source.write_bytes((line_ending + row + line_ending + row).encode("utf-8"))
    output = tmp_path / "output"

    manifest = builder["build"](source, output)

    assert manifest["source_trajectories"] == 2
    assert manifest["trajectories"] == 4
    with (output / "sft_all.v2.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    assert records.count(value) == 2
    assert sum(r["conversations"][-1].get("content") == answer for r in records) == 2
    with (output / "sft_all.v2.turnsplit.jsonl").open(encoding="utf-8") as stream:
        samples = [json.loads(line) for line in stream]
    assert len(samples) == manifest["turnsplit_samples"]
    assert sum(s["messages"][-1]["content"] == answer for s in samples) == 2


def test_build_uses_utf8_with_a_cp949_default(tmp_path, monkeypatch):
    value = record()
    answer = "한글 답변 😀"
    value["conversations"][-2]["tool_calls"][0]["function"]["arguments"] = json.dumps(
        {"answer": answer}, ensure_ascii=False
    )
    source = tmp_path / "input.jsonl"
    source.write_bytes((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    output = tmp_path / "output"
    real_open = io.open

    def cp949_open(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp949"
        return real_open(file, mode, buffering, encoding, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(io, "open", cp949_open)
        manifest = builder["build"](source, output)

    for name in manifest["files"]:
        with (output / name).open(encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream]
        assert rows
        if name != "provenance.jsonl":
            assert answer.encode("utf-8") in (output / name).read_bytes()
    assert (
        json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest
    )
