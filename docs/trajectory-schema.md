# Trajectory schema — format `agent-tracer-1.0`

The structured record of one task run: every model turn, tool call, and
harness action, in wall-clock order, with enough metadata to reconstruct
exactly what the model saw. One file per rollout, written atomically when the
task finishes:

```
<output.path>/trajectories/<task_id>[.s<sample_idx>].traj.json
```

This document describes what `agent_tracer.core.trajectory` writes and
`agent_tracer.recording.recorder` records. The exporters
(`agent-tracer export`) consume nothing outside this schema.

## Envelope

```jsonc
{
  "trajectory_format": "agent-tracer-1.0",
  "task_id": "tw_sample_csv_sum",
  "sample_idx": 0,              // which rollout of this task (best-of-N sampling)
  "metadata": { ... },          // see Metadata
  "events": [ ... ],            // see Events — wall-clock order
  "result": { ... }             // see Result
}
```

## Metadata

Recorded at run time so a trajectory is interpretable without the config that
produced it:

| key | content |
|---|---|
| `dataset` | dataset name (`custom`, `swebench_local`) |
| `orchestrator` | `single` |
| `model` | `{model_name, base_url, reasoning_key}` |
| `environment` | `environment.type` the sandbox ran under |
| `mcp_servers` | `{name: {version, transport}}` for every selected server |
| `agent` | `{role, max_turns}` |
| `system_prompt` | the **assembled** prompt (stirrup base + custom) — exactly what the model saw, required to rebuild training records |
| `tools` | resolved tool specs (OpenAI function format), post provider/MCP resolution |
| `timestamp_start` / `timestamp_end` | UTC ISO 8601 |
| `total_tokens` | `{input, reasoning, answer}` summed over the run |

## Events

Every event carries the same five fields:

```jsonc
{
  "event_id": "e0001",          // sequential per trajectory
  "event_type": "model_response",
  "agent_id": "agent-0",        // null for runner-side events
  "timestamp": "2026-08-14T09:30:00.123456+00:00",
  "data": { ... }               // per-type payload below
}
```

### Event types and payloads

| `event_type` | `data` | emitted when |
|---|---|---|
| `task` | `{content}` | the task input is handed to the agent |
| `user_message` | `{content}` | a real user turn reaches the model |
| `injected_<kind>` | `{content}` | a harness-injected user turn, tagged with its stirrup `kind` — so exporters never mistake synthetic text for a real user turn |
| `thinking` | `{content}` | a reasoning block in a model turn (one event per block) |
| `model_response` | `{turn, content, tool_calls: [{tool_call_id, name, arguments}], usage: {input, reasoning, answer}, duration_s}` | one per model turn; `content` null when the turn was tool-calls only. A turn with no tool call that is not the last is not recorded (nor its `thinking`): the loop answers it with an unrecorded "Please continue the task", so `turn` skips its number |
| `tool_call` | `{tool_call_id, name, arguments}` | one per call, duplicated out of `model_response` for stepwise consumers |
| `tool_result` | `{tool_call_id, name, success, content, duration_s}` | the tool's answer returns to the loop |
| `context_summarization_start` | `{pct_used, cutoff}` | context crossed the summarization cutoff |
| `context_summarization_complete` | `{summary, bridge}` | the summarized context replaced the full one |
| `warning` | `{message}` | a non-fatal harness condition |
| `error` | `{message, attempt?}` | a recorder-level error, or the runner recording a failed attempt |
| `submission` | `{answer}` | the agent called `submit` |

`arguments` is parsed JSON where the model produced valid JSON, otherwise the
raw string — never silently repaired.

## Result

Written once by the runner when the task finishes:

```jsonc
// completed
{ "submission": "3895", "exit_status": "submitted",
  "evaluation": {"correct": true, "score": 1.0, "details": null}, "attempt": 1 }

// gave out
{ "submission": null, "exit_status": "max_turns", "evaluation": {...}, "attempt": 1 }

// failed after retries
{ "submission": null, "exit_status": "error", "error": "TimeoutError: ..." }
```

`exit_status` ∈ `submitted` | `max_turns` | `error`. `evaluation.correct` is
`null` for tasks without a `reference` — unknown is recorded as unknown, never
guessed.

## How exporters read it

- **ShareGPT** (`export -F sharegpt`): `system_prompt` → system turn; `task`
  and `user_message` → user turns; `thinking` events attach to the next
  assistant turn's `thinking` field; `model_response` → assistant turn with
  OpenAI-style `tool_calls`; `tool_result` → tool turn. `injected_<kind>`,
  `warning`, `error`, and summarization events are **never** exported as
  conversation turns.
- **HuggingFace Dataset** (`-F hf`): the ShareGPT records as an Arrow dataset.
- **GRPO JSONL** (`-F grpo`): the record split at the first assistant turn
  into `prompt` / `completion`, with `reward` from `evaluation` and
  `group_id = task_id` for grouping sibling samples.

## Versioning

`trajectory_format` names this contract. Additive changes (new event types,
new metadata keys) keep `agent-tracer-1.0`; anything a consumer of this
document would misread bumps it.
