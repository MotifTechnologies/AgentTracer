# TODO

## Distributed ShareGPT serialization differs from the exporter specification

`datasample/sft_all.jsonl` (1,023 rows, prepared for HF upload) and `dump.json`
use **role-specific key sets**, rather than the current exporter's output:

- system/user: `role, content`
- assistant: `role, content, tool_calls`, plus `thinking` only on turns with
  reasoning (679 of 703 turns). Tool-call-only turns retain `content: null`.
- tool: `role, content, tool_call_id`

The exporter specification (`_MESSAGE_KEYS` in `export/sharegpt.py`) instead
requires all five keys (`role/content/tool_calls/thinking/tool_call_id`) on every
turn, including null values. This is not blanket null removal: assistant
`content: null` remains. It appears to be a separate conversion into the chat
template format expected by the trainer.

- [ ] Find where this format was generated (locate the conversion script).
- [ ] Decide how to align the formats:
      (a) Add role-specific serialization as an official exporter mode and document
      it, making the conversion reproducible from repository code; or
      (b) Keep the uniform five-key format canonical and verify that the public HF
      dataset uses it before publication.
- [ ] Decide how training handles assistant turns without thinking (24/703):
      fill with an empty string or allow the trainer to accept an omitted key.

`datasample/` was an untracked 33 MB working-tree directory including HF cache
files (`.gitattributes`, `.cache`); it was added to `.gitignore`. Distribute data
through the HF dataset repository.

## soffice requires an image containing LibreOffice

The `soffice` server passes `soffice --headless` to `SandboxAccess.exec`, so
LibreOffice must be **inside the sandbox container**. Unlike `pdf` and `xlsx`,
which retrieve bytes and parse them in the server process, LibreOffice is a
system binary that uv/pip cannot install. The other servers' pure-Python
pypdf/openpyxl dependencies are supplied through PEP 723.

Image selection is already supported: a task's `docker_image` overrides the
configured image. Document-conversion seeds can therefore specify it directly,
without separate configs per set. The remaining work is to build that image.

- [ ] Build and publish an image containing LibreOffice.

  ```dockerfile
  FROM python:3.12-slim
  RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc && rm -rf /var/lib/apt/lists/*
  ```

  Full `libreoffice` exceeds 1 GB; writer/calc alone use 400–600 MB. Images are
  fetched per task, so size directly affects pull time.

- [ ] Write seeds using soffice and set their `docker_image` to this image.

## Servers do not declare required sandbox binaries

This generalizes the image problem above. Per-task images make manual checking
harder: instead of verifying one configured image, required binaries must be
matched against images spread across hundreds of seed rows.

Including soffice with an image that lacks it fails **only during a runtime tool
call**, not at startup. The trajectory finishes normally while the tool fails,
violating the fail-fast principle that undeclared tools should not affect traces.

- [x] Declare required binaries in manifests (`requires_binaries: ["soffice"]`)
      and check with `command -v` immediately after sandbox startup, rejecting
      tasks when binaries are absent. Check each task because its `docker_image`
      may override the shared config. A missing binary in the shared image aborts
      the run; in a task-supplied image, only that task is recorded as an error,
      without retry.

## Other items

- [ ] Rename `datasets/swebench_local`: it represents tasks that receive an issue
      and submit a diff, not just SWE. `patch_diff` would be more accurate. This
      path is unused; no current config uses the loader.
- [ ] Add MCP server behavior unit tests. `tests/test_mcp_manifests.py` only checks
      that manifest and implementation tool names match. Removing smoke tests
      removed actual launch-and-call coverage, so behavior bugs such as incorrect
      SQLite JOIN results currently go undetected.
- [ ] Increase seed difficulty. Kimi-K3 achieved 99% accuracy with 1/300 tool
      failures. This may suffice for small-model SFT, but GRPO has no reward
      variance to learn from. RL data needs a separate harder set with distractors,
      ambiguous tool selection, and more hops.
- [ ] Handle ties in `toolcall_log_error_report`. The generator treats the earlier
      timestamp as correct, but the instructions omit that rule. This caused
      three wrong answers in 300 cases. Avoiding tied data is preferable to
      adding another rule.
