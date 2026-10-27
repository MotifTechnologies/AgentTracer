# Functional requirements — agent-tracer

What the framework is required to do, stated as verifiable requirements, each
mapped to the module that satisfies it. This is the reviewed requirements
specification for the AgentTracer package; the trajectory file contract it
refers to is specified separately in [trajectory-schema.md](trajectory-schema.md).

Scope: run agentic tasks against any OpenAI-compatible LLM endpoint, record
every run as a structured trajectory, and export the trajectories as training
datasets — without depending on any single model vendor's API.

## 1. Model integration (LLM Adapter)

| id | requirement | satisfied by |
|---|---|---|
| FR-ADP-1 | Connect to any OpenAI-compatible serving endpoint (vLLM, Ollama, hosted) through configuration only — `base_url`, `api_key`, `model_name` — with no code change per backend. | `models/client.py`, `config/schema.py` |
| FR-ADP-2 | The field carrying a model's reasoning text differs per server; it MUST be configurable per model (`reasoning_key`) and REQUIRED, so a wrong default cannot silently drop reasoning from every trajectory. | `models/client.py` |
| FR-ADP-3 | Secrets are referenced as `env:VAR` and resolved at startup; an unresolvable reference refuses the run before any task starts. | `config/schema.py` (`resolve_env_ref`) |

## 2. Agent execution (Reasoning Engine)

| id | requirement | satisfied by |
|---|---|---|
| FR-ENG-1 | Run a plan → act → observe loop per task with a configurable turn ceiling (`agent.max_turns`); exhausting it closes the trajectory as `max_turns`, never as a success. | `orchestrators/single.py` |
| FR-ENG-2 | A task finishes only through an explicit `submit` tool call; the submission is recorded as its own event. | `orchestrators/single.py` |
| FR-ENG-3 | Tasks run concurrently up to `runner.max_concurrency`, each in an isolated session (client, tools, recorder per task). | `run/runner.py`, `orchestrators/single.py` |
| FR-ENG-4 | Harness-injected turns must never be mistakable for user text in exported data: turn-remaining warnings are disabled, a tool-less turn the loop answers with "Please continue the task" is left out together with that request, and injected turns are tagged with their own event types. | `orchestrators/single.py`, `recording/recorder.py` |

## 3. Tool execution and sandboxing (Tool Executor)

| id | requirement | satisfied by |
|---|---|---|
| FR-EXE-1 | Model-written code executes in an isolated Docker sandbox: no network, memory / pids / execution-time ceilings, restricted mounts. The local backend exists for development only. | `environments/docker.py`, `environments/docker_provider.py` |
| FR-EXE-2 | A task may ship its own `docker_image`; the run uses that image for that task, and refuses a backend that cannot honor it. | `orchestrators/single.py` |
| FR-EXE-3 | Sandbox backends are pluggable through an entry-point registry (`build` / `describe` / `attach`), so an external sandbox service can be added without modifying the package. | `environments/__init__.py` |
| FR-EXE-4 | A binary a tool needs inside the sandbox is declared in its manifest (`requires_binaries`) and probed as soon as the task's sandbox is up; a sandbox that lacks it refuses the task instead of producing a trajectory whose tool quietly failed. | `orchestrators/single.py`, `mcp/discovery.py` |

## 4. MCP tool layer

| id | requirement | satisfied by |
|---|---|---|
| FR-MCP-1 | Tools are provided as MCP servers, auto-discovered from one directory of manifests; a directory without a valid manifest aborts the run (fail-fast), because a silently absent tool corrupts the dataset's tool distribution. | `mcp/discovery.py` |
| FR-MCP-2 | Both stdio (runner-spawned) and streamable-HTTP (externally hosted) transports are supported; the runner narrows the set per run via `mcp.include` / `mcp.exclude`. | `mcp/discovery.py`, `mcp/provider.py` |
| FR-MCP-3 | Servers that work on the agent's files attach to the task's sandbox by id, receiving its description through `AGENT_TRACER_*` variables; backend credentials reach only servers that declare `sandbox_options`. | `mcp/discovery.py`, `environments/__init__.py` |
| FR-MCP-4 | Every server is held to the timeouts its manifest declares: a slow initialize aborts startup with the budget named, and a hung tool call returns to the model as a timeout result rather than ending the trajectory. | `mcp/provider.py` |
| FR-MCP-5 | A manifest's declared tool list must match the server's implementation; drift is caught by contract tests. | `tests/test_mcp_manifests.py` |

## 5. Trajectory recording

| id | requirement | satisfied by |
|---|---|---|
| FR-REC-1 | Every run is recorded as an event stream — model turns, reasoning blocks, tool calls, tool results, harness events — in wall-clock order, in the `agent-tracer-1.0` format. | `recording/recorder.py`, `core/trajectory.py` |
| FR-REC-2 | The recorded metadata must suffice to reconstruct exactly what the model saw: the assembled system prompt and the resolved tool specs are stored per trajectory. | `orchestrators/single.py` |
| FR-REC-3 | Trajectory files are written atomically (temp file + rename), one per rollout, keyed by task id and sample index so repeated sampling never overwrites. | `core/trajectory.py` |
| FR-REC-4 | Token usage (input / reasoning / answer) is totalled per trajectory and streamed to the runner for live throughput display. | `recording/recorder.py`, `run/runner.py` |

## 6. Dataset building and quality (Dataset Builder)

| id | requirement | satisfied by |
|---|---|---|
| FR-DS-1 | Export trajectories to three training formats: ShareGPT JSONL, HuggingFace Dataset, GRPO JSONL. | `export/sharegpt.py`, `export/formats.py` |
| FR-DS-2 | Verifiable tasks are graded against their reference; correctness, score, and exit status are recorded per rollout. An unknown verdict is recorded as unknown, never guessed. | `datasets/custom.py` |
| FR-DS-3 | Rejection sampling: sample each task multiple times (`samples_per_task`), then select at export — drop incorrect rollouts (`--require-correct`) or keep the cheapest correct rollout per task (`--best-per-task`: fewest turns, then fewest tokens, deterministic tie-break). Selection on an ungraded trajectory aborts rather than guessing. | `run/runner.py`, `export/sharegpt.py` |
| FR-DS-4 | Error trajectories are excluded from export by default; selection statistics (dropped, tasks without a correct sample) are reported, not hidden. | `export/sharegpt.py` |

## 7. Operations

| id | requirement | satisfied by |
|---|---|---|
| FR-RUN-1 | Interrupted or repeated runs resume: finished (task, sample) pairs are checkpointed and skipped. | `run/runner.py` |
| FR-RUN-2 | Transient task failures retry with backoff up to a configured ceiling; non-transient configuration failures (a missing sandbox binary on the shared image, a missing secret) abort the run instead of burning retries. | `run/runner.py` |
| FR-RUN-3 | Per-task images are released after their last sample to bound disk use; the shared config image is never released. | `run/runner.py` |
| FR-RUN-4 | Web tools are opt-in; enabling them without a search key refuses the run, because the upstream fallback would silently hand the agent a crippled tool set. | `config/schema.py` |

## Quality criteria for released datasets

A trajectory enters a released dataset only if it conforms to the schema
(consistency), ran to an explicit submission (completeness), and came from a
seed set of the target domain (domain fit). Rejection sampling (FR-DS-3) and
error exclusion (FR-DS-4) enforce the first two mechanically; domain fit is a
property of the seed sets a run is pointed at.

## Revision

Reviewed internally by the project's two maintainers. Changes to a requirement
follow the same path as code: a pull request against this file.
