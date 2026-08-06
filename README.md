# agent-tracer

Run agentic tasks against any OpenAI-compatible LLM endpoint (vLLM first) and
record structured trajectories, exportable as SFT/RL training datasets.

Built on [Stirrup](https://github.com/ArtificialAnalysis/Stirrup) (agent loop,
code-exec sandbox, MCP client) — see `NOTICE` for attribution.

## Quick start

```bash
uv sync
uv run agent-tracer run -f config/example.yaml
uv run agent-tracer export -F sharegpt   # or: -F hf | -F grpo
```

- Config: YAML + `-c key.path=value` overrides. `api_key` accepts `env:VAR`
  references or literals; `reasoning_key` is required per model (fail-fast).
- MCP servers: drop a folder with an `mcp.json` manifest under
  `src/agent_tracer/mcp_servers/` — auto-discovered, default all, narrowed via
  `mcp.include`/`mcp.exclude`. See `src/agent_tracer/mcp_servers/README.md`.
- Sandbox: `environment.type: docker` runs code in an isolated container
  (no network, memory/pids caps).

## Development

```bash
uv run pytest tests/
```
