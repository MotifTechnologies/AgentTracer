# Build plain-answer termination examples

Exported agent trajectories end with a `submit` tool call. To also train ordinary
assistant termination, build a paired dataset without calling a model:

```bash
python scripts/build_sft_v2.py path/to/sft_all.jsonl .cache/sft-v2 --seed 42
```

This stdlib-only script takes exported `conversations`/`tools` JSONL. It preserves
each original and adds one converted copy, then shuffles the 1:1 mixture with the
recorded seed. The output directory must not exist. Unsupported final calls,
mismatched tool IDs, empty answers, or unrecognized system instructions fail
before output is written. It expects the agent-tracer finish instructions; review
custom prompts before using this transformation.

Input and output files use UTF-8. JSONL records are read by physical file lines,
preserving Unicode line and paragraph separators inside JSON strings.

The conversion removes the `submit` schema and its final tool response, and replaces
the final assistant turn with the exact `submit.answer` string. That final message
has neither tool calls nor reasoning. Earlier assistant/tool messages and other tool
schemas remain unchanged. System and task-level user instructions are updated to
request a normal final answer. Embedded SWE issue text after `## Issue` is preserved.

Outputs:

- `sft_all.v2.jsonl`: original and converted trajectories.
- `sft_all.v2.turnsplit.jsonl`: one sample per assistant turn, with `messages` and
  JSON-encoded `tools`; only the target turn retains any existing reasoning.
- `provenance.jsonl`: source row, termination mode, and turn-split sample range.
- `manifest.json`: source/builder/output SHA-256 hashes, seed, and counts.

No answers are generated or corrected. Existing evaluation metadata describes the
source trajectory, not a new execution. This transformation does not add follow-up
user turns and does not establish a benchmark improvement. Group paired examples
by source row (preferably task family) before any train/validation split. Recompute
context-length filtering, packing, and training steps: the unfiltered dataset is
twice as large, and filtering may change the effective mixture.

Generated data belongs outside Git. Keep the source dataset's licensing and
attribution files with distributed outputs; this script does not relicense or
automatically copy them. Uploading data is separate from this offline builder.
