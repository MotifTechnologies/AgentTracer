"""Build paired submit/plain-answer SFT examples without model calls (stdlib only)."""

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def plain_answer(record):
    """Preserve tool history; replace the sole terminal submit with its exact answer."""
    result = copy.deepcopy(record)
    messages = result["conversations"]
    positions = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    if not positions:
        raise ValueError("No assistant message")
    index = positions[-1]
    calls = messages[index].get("tool_calls") or []
    if len(calls) != 1 or calls[0]["function"]["name"] != "submit":
        raise ValueError("Expected a sole final submit call")
    call = calls[0]
    args = call["function"]["arguments"]
    args = json.loads(args) if isinstance(args, str) else args
    if not isinstance(args, dict):
        raise ValueError("submit arguments must be an object")
    if not isinstance(args.get("answer"), str) or not args["answer"]:
        raise ValueError("submit.answer must be a nonempty string")
    trailing = messages[index + 1 :]
    if (
        len(trailing) != 1
        or trailing[0]["role"] != "tool"
        or trailing[0].get("tool_call_id") != call["id"]
    ):
        raise ValueError("Expected exactly one matching terminal tool result")
    if any(
        t["function"]["name"] == "submit"
        for m in messages[:index]
        for t in m.get("tool_calls") or []
    ):
        raise ValueError("Earlier submit calls are unsupported")
    if sum(t["function"]["name"] == "submit" for t in result["tools"]) != 1:
        raise ValueError("Expected exactly one submit tool schema")
    result["tools"] = [t for t in result["tools"] if t["function"]["name"] != "submit"]
    result["conversations"] = [
        *messages[:index],
        {
            "role": "assistant",
            "content": args["answer"],
            "tool_calls": None,
            "thinking": None,
            "tool_call_id": None,
        },
    ]
    for message in result["conversations"]:
        if message["role"] == "system":
            text = message["content"]
            old = "You will need to call a finish tool as your last step, where you will pass your finish reason and any required final fields for that tool."
            ending = "When you are done, call the submit tool with your final answer."
            if old not in text or ending not in text:
                raise ValueError(
                    "Unrecognized system termination instructions; review before converting"
                )
            text = text.replace(
                old,
                "When the current task is complete, stop calling tools and return the final answer as an ordinary assistant message.",
            )
            message["content"] = text.replace(
                ending,
                "When you are done, respond directly with the final answer; do not make another tool call.",
            )
        elif message["role"] == "user":
            # Do not rewrite quoted issue text (which may discuss submitting PRs).
            head, separator, issue = message["content"].partition("\n\n## Issue")
            head = head.replace("Submit only", "Return only").replace(
                "submit only", "return only"
            )
            head = head.replace(
                "submit the fix as a unified git diff (the full `git diff` output) via the submit tool.",
                "return the fix as a unified git diff (the full `git diff` output) in your final answer.",
            )
            if "submit tool" in head or "finish tool" in head:
                raise ValueError("Unrecognized user termination instructions")
            message["content"] = head + separator + issue
    return result


def turn_split(record):
    """Train each assistant turn; retain reasoning only on that target turn."""
    conversation = record["conversations"]
    tools = json.dumps(record.get("tools") or [], ensure_ascii=False)
    for last, turn in enumerate(conversation):
        if turn["role"] != "assistant":
            continue
        yield {
            "messages": [
                {
                    "role": m["role"],
                    "content": m.get("content") or "",
                    "tool_calls": m.get("tool_calls") or None,
                    "tool_call_id": m.get("tool_call_id") or None,
                    "reasoning_content": (m.get("thinking") or None)
                    if index == last
                    else None,
                }
                for index, m in enumerate(conversation[: last + 1])
            ],
            "tools": tools,
        }


def build(source, output, seed=42):
    # Fail on an existing directory, including the input directory: never overwrite data.
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory")
    source_hash = sha256(source)
    records = [
        json.loads(line) for line in source.read_text().splitlines() if line.strip()
    ]
    if not records:
        raise ValueError("Input dataset is empty")
    entries = []
    for index, record in enumerate(records):
        try:
            converted = plain_answer(record)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Source row {index}: {error}") from error
        entries.extend([(index, "submit", record), (index, "plain", converted)])
    if sha256(source) != source_hash:
        raise ValueError("Source changed during build")
    random.Random(seed).shuffle(entries)
    output.mkdir(parents=True)
    count = 0
    with (
        (output / "sft_all.v2.jsonl").open("w") as raw,
        (output / "sft_all.v2.turnsplit.jsonl").open("w") as split,
        (output / "provenance.jsonl").open("w") as provenance,
    ):
        for row, (source_row, mode, record) in enumerate(entries):
            raw.write(json.dumps(record, ensure_ascii=False) + "\n")
            start = count
            for sample in turn_split(record):
                split.write(json.dumps(sample, ensure_ascii=False) + "\n")
                count += 1
            provenance.write(
                json.dumps(
                    {
                        "row": row,
                        "source_row": source_row,
                        "termination": mode,
                        "turnsplit_start": start,
                        "turnsplit_count": count - start,
                    }
                )
                + "\n"
            )
    manifest = {
        "version": "v2",
        "source_sha256": source_hash,
        "seed": seed,
        "source_trajectories": len(records),
        "trajectories": len(entries),
        "turnsplit_samples": count,
        "mix": {"submit": len(records), "plain": len(records)},
        "model_calls": 0,
        "builder_sha256": sha256(Path(__file__)),
        "files": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(output.iterdir())
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "output", type=Path, help="New output directory (must not exist)"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        manifest = build(args.source, args.output, args.seed)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
