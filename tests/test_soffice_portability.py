"""The soffice server's shell commands on both GNU and BSD/macOS userlands.

`_convert` decides whether LibreOffice wrote anything by comparing the output's
mtime before and after, and `convert_document` reports the output's size. Both
used `stat -c`, which macOS does not have, so every conversion on the macOS
local backend was reported as "no output file produced".
"""

import importlib.util
import os
import shutil
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1]
    / "src/agent_tracer/mcp_servers/soffice/server.py"
)


@pytest.fixture(scope="module")
def soffice_module():
    spec = importlib.util.spec_from_file_location("soffice_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def soffice(soffice_module, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACER_ENV_TYPE", "local")
    monkeypatch.setenv("AGENT_TRACER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(soffice_module, "_SANDBOX", None)
    return soffice_module


def test_convert_has_a_bsd_mtime_fallback_and_portable_size(soffice, monkeypatch):
    commands = []

    def fake_run(command, timeout_s):
        commands.append(command)
        if command.startswith("wc -c"):
            return 0, "    1234\n", ""  # BSD wc pads with spaces
        return 0, "", ""

    monkeypatch.setattr(soffice, "_run", fake_run)
    result = soffice.convert_document("report.docx", "pdf")

    script = next(c for c in commands if "--convert-to" in c)
    assert script.count("stat -f %Fm") == 2  # before and after
    assert script.count("stat -c %.Y") == 2
    assert not any(c.startswith("stat -c %s") for c in commands)
    assert result["size_bytes"] == 1234


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_converting_twice_is_seen_as_two_conversions(soffice, tmp_path):
    """Real soffice: the mtime check has to work on the host's own `stat`."""
    (tmp_path / "note.txt").write_text("portable mtime\n")
    first = soffice.convert_document("note.txt", "odt")
    second = soffice.convert_document("note.txt", "odt")
    assert first["output_path"] == second["output_path"]
    # The second run overwrote the file; its own size is the one on disk now.
    assert second["size_bytes"] == os.path.getsize(second["output_path"]) > 0
