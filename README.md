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

## After an interrupted run

Containers are torn down, and images a task brought are released, when a run
ends normally. A run that is killed does neither, so both are left behind —
after a set whose tasks ship their own images, that is easily 100 GB.

```bash
docker ps -aq --filter status=exited | xargs -r docker rm
docker images --format '{{.Repository}}:{{.Tag}}' | grep '^swerebenchv2/' | xargs -r docker rmi
```

Filter rather than pruning: `docker system prune -a` also removes the sandbox
base image and anything else on the host that is not currently running.

Re-running the same command resumes — finished samples are skipped — so
cleaning up first costs nothing.

## Development

```bash
uv run pytest tests/
```

## License

Apache License 2.0 — see `LICENSE`.

`src/agent_tracer/models/client.py` adapts code from
[Stirrup](https://github.com/ArtificialAnalysis/Stirrup) and remains under the
MIT License; `NOTICE` carries that attribution.
