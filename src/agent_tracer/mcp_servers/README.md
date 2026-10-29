# mcp_servers/ — automatic MCP server discovery

At startup, the agent-tracer runner scans this packaged directory (overridable
with `mcp.discovery_dir`) and **registers every discovered MCP server** by default.
Adding a folder adds a server to the agent's toolset; no registration code is needed.

## Conventions

- **One subdirectory = one MCP server.** Its folder name is its server name.
- Each folder must contain an **`mcp.json` manifest** declaring how to start it.
  Schema: [`mcp.schema.json`](./mcp.schema.json), manifest version 1.
- A missing or invalid manifest **aborts the run** instead of skipping the folder.
  This prevents bulk generation with an incomplete toolset.
- Names are used unchanged in YAML `mcp.include` / `mcp.exclude` and tool
  namespaces (`mcp:<server-name>/<tool-name>`).

```text
src/agent_tracer/mcp_servers/
├── README.md          # this guide
├── mcp.schema.json    # manifest JSON Schema
├── echo/              # example server (contract reference)
│   ├── mcp.json
│   ├── server.py
│   └── server.py.lock # pinned PEP 723 dependencies
├── calculator/        # exact arithmetic
├── time/              # current time and timezone conversion
├── filesystem/        # read/write/edit/search files   [sandbox]
├── sqlite/            # query and modify SQLite       [sandbox]
├── soffice/           # LibreOffice document conversion [sandbox]
├── pdf/               # extract PDF text and tables   [sandbox]
├── xlsx/              # read workbooks and edit cells [sandbox]
└── context7/          # library documentation lookup  [external HTTP]

Each stdio server folder contains mcp.json, server.py, and server.py.lock.
An [external HTTP] server has no server.py: the runner does not launch it.
```

Servers marked `[sandbox]` work with agent files and follow the
[Sandbox-aware servers](#sandbox-aware-servers) contract below. Others ignore
sandbox environment variables.

`[external HTTP]` points to another service's endpoint using `transport: http`.
There is no spawned process or sandbox environment; it **depends on the network
and the remote service's availability**. Check those first if calls fail.

`tests/test_mcp_manifests.py` verifies that tools declared in manifests match
those implemented in `server.py`. It compares source without launching servers,
so normal `pytest` catches tools added or renamed on only one side.

> General search and fetch use Stirrup's built-in `web_fetch` / `web_search`,
> not MCP (`tools.web: true`; `web_search` needs `BRAVE_API_KEY`). Adding the
> same functions through MCP exposes duplicate toolsets to the model.
> `context7` serves curated documentation for specific libraries rather than
> arbitrary URLs, so it remains separate. Inspect actual trajectories to see
> whether the overlapping capabilities are both used.

### Why these servers?

Even when `code_exec` can do the same work, dedicated tools change **what the
trajectory records**. `cat -n f | sed -n '20,40p'` records shell proficiency;
`read_file(path=..., offset=20)` records the operation. The latter is more useful
as training data, with the same round-trip cost.

- `filesystem`: `edit_file` has no convenient shell equivalent. Getting `sed -i`
  right is unrelated to the task, and mistakes can silently damage a file.
  This tool rejects edits unless exactly one match exists, reporting the count.
- `sqlite`: models can confidently miscalculate sums and joins. Queries are
  verifiable. Sandbox images often lack the `sqlite3` CLI, so the server uses
  `python3` and its standard-library `sqlite3` module.
- `time`: models have no clock. Recalled offsets fail around DST transitions and
  half-hour offsets such as India (+05:30), often the point of the task.
- `pdf`: `soffice` exports PDFs well but does not read them well; LibreOffice
  treats PDFs as drawings, scrambling or omitting text. Extraction is a separate
  job. `extract_text` can merge table columns and lead to misread numbers, so the
  server separates cells. Pages without text are reported as **apparently
  scanned**, rather than empty strings that suggest an empty document. Detection
  is **per page**: one text-bearing stamp should not hide a 50-page scanned file.
  All four tools, including `search_text`, inspect at most 50 pages per call.
  Extracting 3,000 pages for one unmatched pattern can exceed `call_timeout_s`
  (180 seconds), blocking other calls on the single-threaded stdio server.
- `xlsx`: converting to CSV with `soffice` loses sheets, formulas, and cell
  addresses, which are often the subject of spreadsheet questions. Two pitfalls
  are handled explicitly. **(1) Formula results may be absent.** openpyxl reads
  either formulas or cached results. Files created by scripts and never opened
  in Excel may have no cache; calculated cells then appear as `None`. The server
  returns both representations and identifies formulas without cached values.
  **(2) Round trips can lose content.** Saving through openpyxl reconstructs the
  workbook and may lose charts, images, shapes, pivots, .xlsm macros, and sheet
  `extLst` features such as sparklines and x14 validation. Because many are absent
  from openpyxl's object model, the server **inspects workbook parts directly
  and refuses unsafe writes**. Cell comments survive and do not cause refusal.
  One unavoidable loss is that saving clears the workbook's **formula result
  cache**; the response reports this.
- `read_range` bounds the range **before reading cells**. Outside read-only mode,
  openpyxl can create a Cell for every coordinate in the used range. A 4.8 KB file
  containing only A1 and CZ200000 can therefore consume several GB. The server
  runs outside the sandbox's cgroup limits, so this can exhaust the runner host.
- `context7`: a model's library API knowledge is tied to its training cutoff and
  can confidently use old signatures. Documentation fills this gap, as `time`
  supplies a clock. Its two-step API is `resolve-library-id` → `query-docs`;
  those hyphenated names come from the service specification.

**There is deliberately no git server.** A wrapper helps most when a model is
unfamiliar with the CLI, while git is one of its strongest tools. Exposing writes
(commit, checkout, reset) risks losing a task's working tree. With read-only git,
models still use the shell when committing and perform reads there too. A trial
read-only server showed exactly this: the model used `git rev-list --count`
instead of `git__log`. Leave git operations to `code_exec`.

## Selecting servers in YAML

All servers are registered by default. Narrow the set in domain-specific configs.

```yaml
mcp:
  # discovery_dir: defaults to the packaged mcp_servers/ directory
  include: ["filesystem", "soffice"] # register only these servers
  # exclude: ["echo"]                # alternative; cannot be combined with include
```

Registered servers, tools, and versions are recorded in trajectory metadata.

## Dependency locks and SBOMs

Pin each stdio server's PEP 723 inline dependencies in its adjacent
`server.py.lock`. After adding a server or changing dependencies, generate or
update its lock from the repository root and commit it with the change.

```bash
uv lock --script src/agent_tracer/mcp_servers/pdf/server.py
```

Add `--upgrade-package <package>` to select a patched package version. Updating
the root `uv.lock` does not update these independent environments.

The Security CI `licenses` job uses each packaged stdio server's lock to create
a separate CycloneDX SBOM. The supported launch form is currently
`uv run --quiet server.py`. Missing locks or unsupported launch forms fail the
check; support new launch forms explicitly in the SBOM generator. Checks do not
start servers, agents, or Docker.

External HTTP servers have their exclusion reasons recorded in `index.json`.
A user-supplied `mcp.discovery_dir` is also outside CI's packaged-server scope.
Follow the [SBOM operations guide](../../../docs/sbom.md) for downloads, license
reviews, and distribution notices.

## Sandbox-aware servers

Servers working with agent files must know **which sandbox belongs to the
current task**. Manifests are read once at runner startup, while sandboxes are
created per task, so the manifest cannot name a sandbox that does not yet exist.

The runner passes the identity through **environment variables to every spawned
stdio server** (`sandbox_env` in [`mcp/discovery.py`](../mcp/discovery.py)), using
backend-neutral names:

| Variable | Meaning |
| --- | --- |
| `AGENT_TRACER_ENV_TYPE` | The `environment.type` that created the sandbox |
| `AGENT_TRACER_SANDBOX_ID` | Value for `environments.attach()`; absent for local |
| `AGENT_TRACER_WORKDIR` | Agent working directory inside the sandbox |
| `AGENT_TRACER_HOST_DIR` | Mounted host path, for backends that mount one |
| `AGENT_TRACER_USER` | Sandbox user, for backends that define one |
| `AGENT_TRACER_OPTIONS` | JSON backend-specific values passed directly to `attach()`; **only for manifests declaring `sandbox_options: true`** |

Except for `OPTIONS`, these variables are supplied to **all manifests**, without
opt-in. Missing values are omitted rather than set to `""`; check for presence.
Manifest `env` is merged last and can override them if needed.

`OPTIONS` is opt-in because it can carry backend credentials. Backends retrieve
credentials there; calculation-only or third-party servers do not need them.
Servers that attach to a sandbox declare this requirement in their manifests.
`environment.options` supports `env:VAR_NAME` references resolved at startup;
unresolved references prevent execution.

Call `environments.from_env()` to obtain `(access, workdir)` from these variables.
**Do not branch on backend type**: sandbox plugins should work without changes
to server code.

```python
from agent_tracer.environments import from_env, resolve

access, workdir = from_env()
rc, out, err = access.exec(f"wc -l {resolve('data.csv', workdir)}")
```

`access` provides only `exec(command, timeout_s)`
([`SandboxAccess`](../environments/__init__.py)). It has no file API or lifecycle;
document conversion servers need only a command interface.

**Use `read_bytes` / `write_bytes` for bytes.** They transfer base64 through the
exec interface, sharing the implementation needed by three servers.

```python
from agent_tracer.environments import from_env, read_bytes, resolve

access, workdir = from_env()
raw = read_bytes(access, resolve("report.pdf", workdir))  # exact bytes
```

`pdf` and `xlsx` build on this: **retrieve bytes from the sandbox and parse them
in the server process**. Sandbox images do not need pypdf or openpyxl; each server
declares them in its PEP 723 header, avoiding image-specific failures. Writes are
limited to 1 MiB and reads to 32 MiB; use `code_exec` for larger transfers.

Two safeguards protect byte transfers. **Validate reads**: login-shell output
from `docker exec`, such as MOTD or conda banners, can mix into stdout. Base64
normally discards non-alphabet characters silently, producing corrupted files.
Use `validate=True` and compare decoded length with `stat` size. **Chunk writes
and replace atomically**: the per-argument limit is MAX_ARG_STRLEN (128 KiB),
not ARG_MAX (2 MiB). The whole script is one argument; the observed transfer limit
was 98,244 bytes. Send chunks into an adjacent temporary file, then replace with
`mv`, so an interrupted write does not truncate the original.

These servers import `agent_tracer` for `attach()`, but independent `uv run`
processes do not inherit the runner's interpreter. The runner therefore passes
`PYTHONPATH` too. PEP 723 headers need only each server's actual dependencies.

`soffice/` is the sandbox-aware reference; `calculator/` is the reference that
does not use a sandbox.

## Manifest fields

| Field | Required | Description |
| --- | --- | --- |
| `manifest_version` | Yes | Currently fixed at `1` |
| `name` | Yes | Must match the folder name (`^[a-z][a-z0-9_-]*$`) |
| `description` | Yes | One-line summary recorded in trajectory metadata |
| `transport` | Yes | `stdio` \| `http` |
| `command` / `args` | For stdio | Command spawned by the runner; relative paths resolve from the manifest folder |
| `url` | For HTTP | Streamable HTTP endpoint; server lifecycle is managed externally |
| `env` | No | Spawn environment for stdio. Secrets must use `"env:VAR_NAME"` references; never store literal secrets. Unresolved references prevent execution |
| `headers` | No | HTTP-only per-request headers. Like `env`, `env:` references resolve at startup and failure prevents execution; other values are sent literally. A literal API key exposes it in the repository. Even an empty headers object is rejected for stdio |
| `sandbox_options` | No | Declares that this stdio server attaches to the sandbox. Only opted-in servers receive `AGENT_TRACER_OPTIONS` (backend credentials) |
| `startup_timeout_s` | No | Initialize-handshake timeout, default 15 seconds. Selected servers connect sequentially, so the total upper bound is the **sum** of their manifest values. A timeout aborts that attempt |
| `call_timeout_s` | No | Tool-call timeout, default 60 seconds, for stdio and HTTP. Timed-out calls are cancelled and returned to the model as timeout results; the trajectory continues |
| `tools` | No | Declarative tool list for documentation and contract tests; runtime truth comes from MCP discovery |

## Example: echo server

[`echo/`](./echo/) is the minimal working contract reference. Copy its structure
when creating a server.

```bash
# Standalone invocation, matching the runner's launch method
cd src/agent_tracer/mcp_servers/echo && uv run server.py
```

Implement servers with the official MCP Python SDK (FastMCP) and declare
dependencies as PEP 723 inline metadata. A single `uv run` then starts the server,
without manually managing one virtual environment per folder.
