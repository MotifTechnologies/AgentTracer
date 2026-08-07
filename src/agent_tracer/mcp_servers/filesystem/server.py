# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Reading and writing the agent's files, as tool calls rather than shell.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

The agent can already do all of this with `code_exec`, so the argument for the
server is what the trajectory looks like afterwards. `cat -n file | sed -n
'20,40p'` records the model's shell fluency; `read_file(path=..., offset=20)`
records the step. For data meant to be trained on, the second is the one worth
keeping, and it is the same round trip either way.

`edit_file` is the tool that does not have a good shell equivalent. Getting a
`sed -i` right on the first try is a skill unrelated to the task, and getting it
wrong corrupts the file silently. Here an edit that does not match exactly once
is refused, with the count.

Content moves base64-encoded. Going through a shell means text is all that comes
back, and a task's files are not reliably UTF-8 — a latin-1 CSV or a stray byte
would otherwise arrive mangled, or kill the call.
"""

import base64
import shlex

from mcp.server import MCPServer

from agent_tracer.environments import from_env, resolve

mcp = MCPServer(name="filesystem", version="0.1.0")

DEFAULT_TIMEOUT_S = 60

#: A write is sent as one shell command, so the encoded content has to fit in
#: the argument list. ARG_MAX is 2 MiB on Linux and the command carries more
#: than the payload, so this leaves generous headroom. Anything larger is a job
#: for `code_exec`, and saying so beats "Argument list too long".
MAX_WRITE_BYTES = 1 << 20

#: `read_file` truncates rather than returning a whole file: a 200 MB log
#: otherwise arrives as one tool result and takes the context window with it.
DEFAULT_READ_LIMIT = 2000

_SANDBOX = None


def _sandbox():
    """The sandbox and its working directory, opened once and reused."""
    global _SANDBOX
    if _SANDBOX is None:
        _SANDBOX = from_env()
    return _SANDBOX


def _run(command: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> tuple[int, str, str]:
    return _sandbox()[0].exec(command, timeout_s=timeout_s)


def _abs(path: str) -> str:
    return resolve(path, _sandbox()[1])


def _read_bytes(path: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> bytes:
    """The file's exact bytes, whatever encoding it happens to be in."""
    # `-w0` matters: GNU base64 wraps at 76 columns by default and the newlines
    # would have to be stripped back out.
    rc, out, err = _run(f"base64 -w0 {shlex.quote(path)}", timeout_s)
    if rc != 0:
        raise FileNotFoundError(f"Could not read {path}: {(err.strip() or out.strip())[:200]}")
    return base64.b64decode(out.strip())


def _write_bytes(path: str, content: bytes, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
    if len(content) > MAX_WRITE_BYTES:
        raise ValueError(
            f"{len(content)} bytes is larger than this tool writes ({MAX_WRITE_BYTES}). "
            "Generate the file with code_exec instead."
        )
    encoded = base64.b64encode(content).decode("ascii")
    parent = path.rsplit("/", 1)[0] or "/"
    script = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}"
    )
    rc, out, err = _run(script, timeout_s)
    if rc != 0:
        raise RuntimeError(f"Could not write {path}: {(err.strip() or out.strip())[:200]}")


def _decode(raw: bytes) -> str:
    """Text for the model, without failing on a file that is not quite UTF-8."""
    return raw.decode("utf-8", errors="replace")


@mcp.tool()
def read_file(path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> dict:
    """Read a text file, a window of lines at a time.

    Args:
        path: File to read, absolute or relative to the working directory.
        offset: First line to return, 0-based. Use with `limit` to page.
        limit: Maximum number of lines to return.
    """
    if offset < 0 or limit < 1:
        raise ValueError("offset must be >= 0 and limit >= 1")

    lines = _decode(_read_bytes(_abs(path))).splitlines()
    window = lines[offset : offset + limit]
    return {
        "path": _abs(path),
        "content": "\n".join(window),
        "total_lines": len(lines),
        "returned_lines": len(window),
        # So the model knows to page rather than assuming it saw the file.
        "truncated": offset + len(window) < len(lines),
    }


@mcp.tool()
def write_file(path: str, content: str) -> dict:
    """Write text to a file, replacing it if it exists.

    Parent directories are created. To change part of an existing file, prefer
    `edit_file` — it cannot silently drop the rest.

    Args:
        path: File to write, absolute or relative to the working directory.
        content: The full new contents.
    """
    target = _abs(path)
    _write_bytes(target, content.encode("utf-8"))
    return {"path": target, "bytes_written": len(content.encode("utf-8"))}


@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """Replace an exact string in a file.

    Refuses unless `old_string` appears exactly once, so an edit meant for one
    place cannot quietly land in several. Pass `replace_all` when every
    occurrence is intended.

    Args:
        path: File to edit, absolute or relative to the working directory.
        old_string: Text to replace. Must match exactly, including whitespace.
        new_string: Replacement text.
        replace_all: Replace every occurrence instead of requiring exactly one.
    """
    target = _abs(path)
    text = _decode(_read_bytes(target))
    count = text.count(old_string)

    if count == 0:
        raise ValueError(f"{old_string!r} does not appear in {target} — nothing was changed.")
    if count > 1 and not replace_all:
        raise ValueError(
            f"{old_string!r} appears {count} times in {target}. Include enough "
            "surrounding text to make it unique, or pass replace_all=true."
        )

    _write_bytes(target, text.replace(old_string, new_string).encode("utf-8"))
    return {"path": target, "replacements": count if replace_all else 1}


@mcp.tool()
def list_directory(path: str = ".") -> dict:
    """List a directory's entries, marking which are directories.

    Args:
        path: Directory to list, absolute or relative to the working directory.
    """
    target = _abs(path)
    # `-p` appends `/` to directories, which is what distinguishes them here.
    rc, out, err = _run(f"ls -Ap {shlex.quote(target)}")
    if rc != 0:
        raise FileNotFoundError(f"Could not list {target}: {(err.strip() or out.strip())[:200]}")

    entries = [
        {"name": line.rstrip("/"), "type": "directory" if line.endswith("/") else "file"}
        for line in out.splitlines()
        if line
    ]
    return {"path": target, "entries": entries, "count": len(entries)}


@mcp.tool()
def file_info(path: str) -> dict:
    """Size, type and modification time of a file or directory.

    Args:
        path: Path to inspect, absolute or relative to the working directory.
    """
    target = _abs(path)
    rc, out, _ = _run(f"stat -c '%s|%F|%Y' {shlex.quote(target)}")
    if rc != 0:
        raise FileNotFoundError(f"No such file or directory: {target}")

    size, kind, mtime = out.strip().split("|", 2)
    return {"path": target, "size_bytes": int(size), "type": kind, "mtime_epoch": int(mtime)}


@mcp.tool()
def search_files(pattern: str, path: str = ".", max_results: int = 100) -> dict:
    """Find files whose name matches a glob, recursively.

    Args:
        pattern: Filename glob, e.g. "*.csv" or "test_*.py".
        path: Directory to search under.
        max_results: Stop after this many matches.
    """
    target = _abs(path)
    rc, out, err = _run(
        f"find {shlex.quote(target)} -name {shlex.quote(pattern)} -type f 2>/dev/null | "
        f"head -n {int(max_results)}"
    )
    if rc != 0 and not out:
        raise RuntimeError(f"Search failed in {target}: {err.strip()[:200]}")

    matches = [line for line in out.splitlines() if line]
    return {"pattern": pattern, "matches": matches, "count": len(matches)}


@mcp.tool()
def search_content(pattern: str, path: str = ".", max_results: int = 100) -> dict:
    """Find lines matching a regular expression, recursively.

    Args:
        pattern: Extended regular expression to search for.
        path: File or directory to search.
        max_results: Stop after this many matching lines.
    """
    target = _abs(path)
    # `-H` because grep omits the filename prefix when it is given exactly one
    # file operand, even under `-r` — and every match here is parsed on it.
    rc, out, err = _run(
        f"grep -rHnIE {shlex.quote(pattern)} {shlex.quote(target)} 2>/dev/null | "
        f"head -n {int(max_results)}"
    )
    # grep exits 1 for "no matches", which is an answer rather than a failure.
    if rc > 1 and not out:
        raise RuntimeError(f"Search failed in {target}: {err.strip()[:200]}")

    matches = []
    for line in out.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3:
            matches.append({"path": parts[0], "line": int(parts[1]), "text": parts[2]})
    return {"pattern": pattern, "matches": matches, "count": len(matches)}


@mcp.tool()
def move_file(source: str, destination: str) -> dict:
    """Move or rename a file or directory.

    Args:
        source: Path to move, absolute or relative to the working directory.
        destination: Where to move it to.
    """
    src, dst = _abs(source), _abs(destination)
    parent = dst.rsplit("/", 1)[0] or "/"
    rc, out, err = _run(f"mkdir -p {shlex.quote(parent)} && mv {shlex.quote(src)} {shlex.quote(dst)}")
    if rc != 0:
        raise RuntimeError(f"Could not move {src}: {(err.strip() or out.strip())[:200]}")
    return {"source": src, "destination": dst}


@mcp.tool()
def create_directory(path: str) -> dict:
    """Create a directory, including any missing parents.

    Args:
        path: Directory to create, absolute or relative to the working directory.
    """
    target = _abs(path)
    rc, out, err = _run(f"mkdir -p {shlex.quote(target)}")
    if rc != 0:
        raise RuntimeError(f"Could not create {target}: {(err.strip() or out.strip())[:200]}")
    return {"path": target}


if __name__ == "__main__":
    mcp.run(transport="stdio")
