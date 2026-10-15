# Native FC synthesis fixtures

`dataset.name: bfcl_fixture` selects a native-message orchestrator and deterministic typed tool backend. It reuses the tracer client, trajectory recorder, Runner and ShareGPT exporter. This is an independent synthesis adapter, not BFCL's official scorer or dataset loader.

The fixture JSONL contains task_id, category, optional system_prompt, tools (native function schema plus declarative operation), initial_state, user_turns and provenance. Only explicit system/user messages and native function schemas reach the model. State, witness, expected_state and provenance do not. No default Stirrup prompt, submit, code_exec, turn warning or summarizer is added. A response with no tool calls ends the current user turn; the next scripted user turn continues the same state/history. Provider call IDs and reasoning_details are preserved. Tool outputs come from deterministic code, never teacher-authored messages.

Supported operations are query, get, update, create, delete and bounded calculations. JSON Schema validates arguments (including dates); fixture state is isolated per rollout. A turn can require an exact full state, answer anchors, tool capabilities and a parallel call batch. Exact text state and substring answer anchors are deliberately narrow checks: they do not establish semantic correctness. Review user intent and goals independently before collecting data; permit valid alternative plans rather than requiring the witness sequence. Full-state equality can reject equivalent free-text updates. Never label an unreviewed oracle or automatic result training-ready.

Tool schemas must be self-contained: references use root-local `#` fragments, and `$id` scope changes are rejected throughout the schema document. Validation uses an offline registry that never fetches HTTP or file references. Local `$defs` references remain supported; this is a restricted schema subset, not arbitrary JSON Schema resource loading.

Use the normal CLI with a reviewed fixture file and a config containing `runner.retry.max_attempts: 1`, `model.max_retries: 0`, and `model.api_key: env:YOUR_KEY`. Example commands:

```bash
uv run agent-tracer run -f config/bfcl-fixture-example.yaml
uv run agent-tracer export -t results/bfcl-fixture/trajectories --require-correct --best-per-task -o results/bfcl-fixture/automatic-candidates.jsonl
```

Export selection only means the configured grader passed. Manual intent/grounding/diversity review and an offline evaluation-content exclusion screen are separate adoption gates. Strict-clean mode rejects every invalid/error/repeated nonprogressing tool call, even if a later response recovers; do not claim error-recovery training coverage from that policy.

`model.send_max_tokens: false` omits the output-budget parameter. It does not establish the provider default or promise an unlimited output. Verify provider behavior and reasoning in a real smoke. A length finish remains raw-recorded in the native adapter and is rejected before executing partial tool calls. Existing legacy client callers keep their OutputTokenLimitError behavior.

Fixture output is bound to dataset bytes, model configuration hash, agent and runner settings. Raw request/response journals append and flush per request. Resume refuses changed bindings, unmatched requests, or any existing API journal without a terminal sample result. Inspect uncertain provider requests and recover saved responses offline; do not blindly repeat paid calls. An exclusive `.fixture-collector.lock` reservation prevents concurrent fixture collectors from using one output directory. Input bindings and journals are rechecked while holding that reservation. A crash may leave the lock: inspect owned processes and journals before explicit recovery; locks are never automatically stolen.

The checked-in inventory example was independently written for this adapter and is covered by the repository Apache-2.0 license. It contains no downloaded benchmark questions, public seed rows, teacher responses, or provider-specific generation settings. Configure the endpoint and model for your own deployment; the example does not claim compatibility with every model or any permission to use that model's outputs.

Adapter code and generated datasets have separate provenance requirements. Record source URL and pinned revision, source license and attribution, generator model revision and applicable model/provider terms, output-use permissions, and review decisions before adopting or redistributing data. A permissive seed license alone does not settle teacher-output rights. Do not commit API keys, downloaded seeds, requests, responses, trajectories, or generated candidates. Keep held-out evaluation content out of author prompts and training exports; a lexical screen does not establish absence of semantic contamination.

The provisional state and answer-anchor checks remain diagnostic filters. They are not a legal clearance, semantic correctness guarantee, or official BFCL score. A data collection should explicitly stop at its approved pilot scope until intent, grounding, alternative valid plans, diversity, and provenance have been reviewed.
