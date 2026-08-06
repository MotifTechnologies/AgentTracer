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

Content moves base64-encoded, via `environments.read_bytes`/`write_bytes`: a
shell hands back text, and a task's files are not reliably UTF-8 — a latin-1 CSV
or a stray byte would otherwise arrive mangled, or kill the call.
"""

import base64
import shlex

from mcp.server import MCPServer

from agent_tracer.environments import from_env, read_bytes, resolve, write_bytes

mcp = MCPServer(name="filesystem", version="0.1.0")

DEFAULT_TIMEOUT_S = 60

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


def _read(path: str) -> bytes:
    return read_bytes(_sandbox()[0], path, timeout_s=DEFAULT_TIMEOUT_S)


def _write(path: str, content: bytes) -> None:
    write_bytes(_sandbox()[0], path, content, timeout_s=DEFAULT_TIMEOUT_S)


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

    # Split on "\n" and nothing else. `str.splitlines()` also breaks on \v \f
    # \x1c-\x1e \x85     and a bare \r, and the window is rejoined
    # with "\n" — so a file holding any of them was counted as more lines than
    # it has, paged by boundaries that are not there, and handed to the model
    # as bytes it does not contain.
    lines = _decode(_read(_abs(path))).split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # a trailing newline ends the last line, it does not start one
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
    _write(target, content.encode("utf-8"))
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
    # Matched and replaced as bytes. Decoding with errors="replace" and writing
    # the result back turns every byte that is not UTF-8 into U+FFFD — in the
    # whole file, not just the edited part — which is the silent corruption
    # this tool exists to avoid. A file that is not UTF-8 at all simply does
    # not match a non-ASCII `old_string`, and says so.
    raw = _read(target)
    old, new = old_string.encode("utf-8"), new_string.encode("utf-8")
    count = raw.count(old)

    if count == 0:
        raise ValueError(f"{old_string!r} does not appear in {target} — nothing was changed.")
    if count > 1 and not replace_all:
        raise ValueError(
            f"{old_string!r} appears {count} times in {target}. Include enough "
            "surrounding text to make it unique, or pass replace_all=true."
        )

    _write(target, raw.replace(old, new) if replace_all else raw.replace(old, new, 1))
    return {"path": target, "replacements": count if replace_all else 1}


@mcp.tool()
def list_directory(path: str = ".") -> dict:
    """List a directory's entries, marking which are directories.

    Args:
        path: Directory to list, absolute or relative to the working directory.
    """
    target = _abs(path)
    quoted = shlex.quote(target)
    # A filename is bytes, and `ls` writes it out as it is. The backends' `exec`
    # decodes strictly, so one byte that is not UTF-8 anywhere in the directory
    # killed the whole call; and splitting that output on newlines made `a\nb`
    # — a legal name — into two entries. So names cross the way file content
    # does: NUL-separated, base64'd, decoded here, where a byte that is not
    # UTF-8 can be replaced in the one name that holds it.
    #
    # The glob is `ls -A`: everything except `.` and `..`. The existence test
    # is what skips a pattern that matched nothing, and `-L` keeps a broken
    # symlink, which is an entry of the directory like any other.
    #
    # `ls` on a plain file lists that file, which came back as a directory
    # holding one entry whose name was the whole absolute path.
    rc, out, err = _run(
        f"if [ ! -e {quoted} ]; then echo 'no such directory' >&2; exit 21; fi; "
        f"if [ ! -d {quoted} ]; then echo 'not a directory' >&2; exit 22; fi; "
        f"cd {quoted} && for entry in * .[!.]* ..?*; do "
        '[ -e "$entry" ] || [ -L "$entry" ] || continue; '
        'if [ -d "$entry" ]; then printf \'d %s\\0\' "$entry"; '
        'else printf \'f %s\\0\' "$entry"; fi; '
        "done | base64 -w0"
    )
    if rc != 0:
        raise FileNotFoundError(f"Could not list {target}: {(err.strip() or out.strip())[:200]}")

    entries = []
    for record in base64.b64decode(out.strip()).split(b"\0"):
        if not record:
            continue
        kind, _, name = record.partition(b" ")
        entries.append(
            {
                "name": _decode(name),
                "type": "directory" if kind == b"d" else "file",
            }
        )
    entries.sort(key=lambda entry: entry["name"])
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
        path: Directory to search under. Must exist.
        max_results: Stop after this many matches.
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")

    target = shlex.quote(_abs(path))
    # The directory is checked here rather than left to `find`: `head` ends the
    # pipeline, so its exit code is the one that comes back and find's is lost —
    # a directory that is not there would read as one with nothing in it.
    rc, out, err = _run(
        f"[ -d {target} ] || {{ echo 'no such directory' >&2; exit 21; }}; "
        f"find {target} -name {shlex.quote(pattern)} -type f 2>/dev/null | "
        f"head -n {max_results}"
    )
    if rc != 0:
        raise RuntimeError(f"Search failed in {_abs(path)}: {(err.strip() or out.strip())[:200]}")

    matches = [line for line in out.splitlines() if line]
    return {"pattern": pattern, "matches": matches, "count": len(matches)}


@mcp.tool()
def search_content(pattern: str, path: str = ".", max_results: int = 100) -> dict:
    """Find lines matching a regular expression, recursively.

    Args:
        pattern: Extended regular expression to search for.
        path: File or directory to search. Must exist.
        max_results: Stop after this many matching lines.
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")

    target = shlex.quote(_abs(path))
    # `-H` because grep omits the filename prefix when it is given exactly one
    # file operand, even under `-r` — and every match here is parsed on it.
    # `-Z` because the prefix is otherwise ended by ":", which a filename is
    # allowed to contain. The path is checked here for the same reason as in
    # search_files: `head` ends the pipeline and grep's exit code is lost, so a
    # path that is not there would read as a file with no matches in it.
    rc, out, err = _run(
        f"[ -e {target} ] || {{ echo 'no such file or directory' >&2; exit 21; }}; "
        f"grep -rHnIEZ {shlex.quote(pattern)} {target} 2>/dev/null | "
        f"head -n {max_results}"
    )
    if rc != 0:
        raise RuntimeError(f"Search failed in {_abs(path)}: {(err.strip() or out.strip())[:200]}")

    matches = []
    for line in out.splitlines():
        name, _, rest = line.partition("\0")
        number, _, text = rest.partition(":")
        if number.isdigit():
            matches.append({"path": name, "line": int(number), "text": text})
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
