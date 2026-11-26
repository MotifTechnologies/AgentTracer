"""The filesystem server's shell commands on both GNU and BSD/macOS userlands.

The local backend runs `grep` and `stat` from the host, so on macOS it gets the
BSD (or, since macOS 26, ugrep) flavours, where `grep -Z` means "decompress" and
`stat -c` does not exist. The real-backend tests below run on whatever host the
suite runs on; the canned-output tests pin the BSD path on a Linux CI as well.
"""

import importlib.util
import os
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1]
    / "src/agent_tracer/mcp_servers/filesystem/server.py"
)


@pytest.fixture(scope="module")
def fs_module():
    spec = importlib.util.spec_from_file_location("filesystem_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fs(fs_module, tmp_path, monkeypatch):
    """The server attached to a fresh local sandbox rooted at tmp_path."""
    monkeypatch.setenv("AGENT_TRACER_ENV_TYPE", "local")
    monkeypatch.setenv("AGENT_TRACER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(fs_module, "_SANDBOX", None)
    (tmp_path / "notes.txt").write_text("hello world\n")
    return fs_module


def test_search_content_finds_matches_on_the_local_backend(fs, tmp_path):
    result = fs.search_content("hello")
    assert result["count"] == 1
    match = result["matches"][0]
    # grep echoes the operand, so a search of "." reports "<dir>/./notes.txt".
    assert os.path.normpath(match["path"]) == str(tmp_path / "notes.txt")
    assert (match["line"], match["text"]) == (1, "hello world")


def test_search_content_keeps_a_colon_in_the_filename(fs, tmp_path):
    (tmp_path / "a:b.txt").write_text("x\nneedle\n")
    [match] = fs.search_content("needle")["matches"]
    assert os.path.normpath(match["path"]) == str(tmp_path / "a:b.txt")
    assert (match["line"], match["text"]) == (2, "needle")


def test_file_info_reports_a_file_on_the_local_backend(fs, tmp_path):
    info = fs.file_info("notes.txt")
    assert info["path"] == str(tmp_path / "notes.txt")
    assert info["size_bytes"] == len("hello world\n")
    assert info["type"] == "regular file"
    assert info["mtime_epoch"] > 0


def test_file_info_reports_a_directory_on_the_local_backend(fs, tmp_path):
    (tmp_path / "sub").mkdir()
    assert fs.file_info("sub")["type"] == "directory"


def test_file_info_on_a_missing_path_is_not_found(fs):
    with pytest.raises(FileNotFoundError):
        fs.file_info("missing.txt")


def test_file_info_falls_back_to_bsd_stat(fs, monkeypatch):
    """What a macOS host prints: `-c` fails, `stat -f '%z|%HT|%m'` answers."""
    seen = []

    def bsd_run(command, timeout_s=60):
        seen.append(command)
        return 0, "12|Regular File|1700000000\n", ""

    monkeypatch.setattr(fs, "_run", bsd_run)
    info = fs.file_info("notes.txt")
    assert "stat -f '%z|%HT|%m'" in seen[0]
    assert info["size_bytes"] == 12
    assert info["type"] == "regular file"
    assert info["mtime_epoch"] == 1700000000


def test_search_content_does_not_use_the_short_z_flag(fs, monkeypatch):
    """`-Z` is "decompress" on macOS grep; only `--null` means NUL everywhere."""
    seen = []

    def record(command, timeout_s=60):
        seen.append(command)
        return 0, "", ""

    monkeypatch.setattr(fs, "_run", record)
    fs.search_content("hello")
    grep = seen[0][seen[0].index("grep ") :].split(" ", 2)[1]
    assert "Z" not in grep
    assert "--null" in seen[0]
