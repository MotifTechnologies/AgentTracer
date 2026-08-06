# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Document conversion, run against the sandbox the task is using.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

LibreOffice runs inside the sandbox, where the agent's files are. This process
stays outside it and sends commands, which is not the obvious arrangement — the
obvious one is to run the server in the sandbox and tunnel its stdio out. That
costs more than it looks: an MCP stdio session stays open for the life of the
agent, so on any backend that meters concurrent sessions it holds one the whole
time, whether or not a conversion is running. From out here a session is taken
only for the seconds a conversion takes.

Which sandbox is this task's arrives in the environment (see mcp/discovery.py),
and reaching it is `environments.attach()`. Deliberately not a branch on
backend: a sandbox installed as a plugin then works here with no change to this
file, which is the point of the registry.
"""

import json
import os
import shlex

from mcp.server import MCPServer

from agent_tracer.environments import attach

mcp = MCPServer(name="soffice", version="0.1.0")

ENV_TYPE = os.environ.get("AGENT_TRACER_ENV_TYPE", "local")
SANDBOX_ID = os.environ.get("AGENT_TRACER_SANDBOX_ID", "")
WORKDIR = os.environ.get("AGENT_TRACER_WORKDIR", "/home/user")
OPTIONS = json.loads(os.environ.get("AGENT_TRACER_OPTIONS", "{}"))

DEFAULT_TIMEOUT_S = 120

# A permissive allowlist, not an exhaustive one: it keeps an obvious typo from
# reaching the converter as a silent no-op.
SUPPORTED_TARGET_FORMATS = frozenset(
    {
        "pdf", "docx", "doc", "odt", "rtf", "txt", "html", "epub",
        "xlsx", "xls", "ods", "csv",
        "pptx", "ppt", "odp",
        "png", "jpg", "svg",
    }
)  # fmt: skip


_ACCESS = None


def _sandbox():
    """Access to the sandbox, opened once and reused across calls.

    Deferred rather than opened at import: a backend may hold a connection, and
    a server that is started but never called should not cost one.
    """
    global _ACCESS
    if _ACCESS is None:
        _ACCESS = attach(ENV_TYPE, SANDBOX_ID, OPTIONS)
    return _ACCESS


def _run(command: str, timeout_s: int) -> tuple[int, str, str]:
    """Run a shell command where the agent's files are."""
    return _sandbox().exec(command, timeout_s=timeout_s)


def _abs(path: str) -> str:
    """Relative paths resolve against the agent's working directory."""
    return path if path.startswith("/") else f"{WORKDIR.rstrip('/')}/{path}"


def _convert(source: str, to_format: str, out_dir: str, timeout_s: int) -> str:
    """Convert `source` into `to_format` under `out_dir`; return the new path."""
    stem = source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    expected = f"{out_dir}/{stem}.{to_format.split(':')[0]}"

    # One command, one trip. Each conversion gets a throwaway user profile:
    # LibreOffice locks its profile, so two sharing one serialise or fail, and a
    # sandbox may be running several conversions.
    #
    # `soffice` reports success even when it silently writes nothing, so the
    # marker is the output file's mtime rather than the exit code.
    script = (
        "set -e; "
        'profile=$(mktemp -d); trap "rm -rf $profile" EXIT; '
        f"mkdir -p {shlex.quote(out_dir)}; "
        f"before=$(stat -c %Y {shlex.quote(expected)} 2>/dev/null || echo none); "
        'soffice "-env:UserInstallation=file://$profile" --headless --norestore '
        f"--nolockcheck --convert-to {shlex.quote(to_format)} "
        f"--outdir {shlex.quote(out_dir)} {shlex.quote(source)}; "
        f"after=$(stat -c %Y {shlex.quote(expected)} 2>/dev/null || echo none); "
        '[ "$after" != "none" ] || { echo "no output file produced" >&2; exit 90; }; '
        '[ "$before" != "$after" ] || { echo "existing file left untouched" >&2; exit 91; }'
    )
    rc, out, err = _run(script, timeout_s)
    if rc != 0:
        detail = (err.strip() or out.strip())[:400]
        raise RuntimeError(f"Conversion failed (exit {rc}): {detail}")
    return expected


@mcp.tool()
def convert_document(
    path: str,
    to_format: str,
    output_dir: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Convert a document to another office format.

    Args:
        path: Source file, absolute or relative to the working directory.
        to_format: Target extension, e.g. "pdf", "docx", "xlsx", "csv".
        output_dir: Directory for the result. Defaults to the source's directory.
        timeout_s: Abort the conversion after this many seconds.
    """
    source = _abs(path)
    fmt = to_format.lower().lstrip(".")
    base_fmt = fmt.split(":")[0]
    if base_fmt not in SUPPORTED_TARGET_FORMATS:
        raise ValueError(
            f"Unsupported target format {base_fmt!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_TARGET_FORMATS))}"
        )

    rc, _, _ = _run(f"test -f {shlex.quote(source)}", 30)
    if rc != 0:
        raise FileNotFoundError(f"No such file in the sandbox: {source}")

    out_dir = _abs(output_dir) if output_dir else source.rsplit("/", 1)[0] or "/"
    result = _convert(source, fmt, out_dir, timeout_s)

    _, size, _ = _run(f"stat -c %s {shlex.quote(result)}", 30)
    return {"output_path": result, "size_bytes": int(size.strip() or 0), "format": base_fmt}


@mcp.tool()
def extract_text(path: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Extract plain text from a document.

    Converts to UTF-8 text in a scratch directory, so the source file and its
    directory are left untouched.

    Args:
        path: Source file, absolute or relative to the working directory.
        timeout_s: Abort the conversion after this many seconds.
    """
    source = _abs(path)
    rc, _, _ = _run(f"test -f {shlex.quote(source)}", 30)
    if rc != 0:
        raise FileNotFoundError(f"No such file in the sandbox: {source}")

    rc, scratch, err = _run("mktemp -d", 30)
    if rc != 0:
        raise RuntimeError(f"Could not make a scratch directory: {err.strip()[:200]}")
    scratch = scratch.strip()
    try:
        # The UTF8 filter is not optional: without it LibreOffice guesses the
        # encoding and mangles non-ASCII text, which is the common case here.
        produced = _convert(source, "txt:Text (encoded):UTF8", scratch, timeout_s)
        rc, text, err = _run(f"cat {shlex.quote(produced)}", timeout_s)
        if rc != 0:
            raise RuntimeError(f"Could not read the extracted text: {err.strip()[:200]}")
    finally:
        _run(f"rm -rf {shlex.quote(scratch)}", 30)

    return {"text": text, "char_count": len(text)}


@mcp.tool()
def list_supported_formats() -> dict:
    """List the target formats convert_document accepts."""
    return {"formats": sorted(SUPPORTED_TARGET_FORMATS)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
