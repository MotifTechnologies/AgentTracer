"""Behaviour tests for the bundled soffice server, called directly.

The conversions run the real `soffice --headless` against the local
backend, so the whole module is skipped when LibreOffice is not installed.
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1]
    / "src/agent_tracer/mcp_servers/soffice/server.py"
)

pytestmark = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="LibreOffice (soffice) is not installed"
)

KNOWN_CONTENT = "agent-tracer soffice behaviour fixture"


@pytest.fixture()
def soffice_server(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACER_WORKDIR", str(tmp_path))
    monkeypatch.delenv("AGENT_TRACER_ENV_TYPE", raising=False)
    spec = importlib.util.spec_from_file_location("soffice_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def docx_path(soffice_server, tmp_path):
    """A small DOCX with known content, built by soffice itself."""
    source = tmp_path / "fixture.txt"
    source.write_text(KNOWN_CONTENT, encoding="utf-8")
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--norestore",
            "--convert-to",
            "docx",
            "--outdir",
            str(tmp_path),
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    produced = tmp_path / "fixture.docx"
    assert produced.exists()
    return produced


def test_list_supported_formats(soffice_server):
    result = soffice_server.list_supported_formats()
    assert "pdf" in result["formats"]
    assert "docx" in result["formats"]
    assert result["formats"] == sorted(result["formats"])


def test_convert_document_docx_to_pdf(soffice_server, docx_path):
    result = soffice_server.convert_document(str(docx_path), "pdf")
    output = Path(result["output_path"])
    assert output.suffix == ".pdf"
    assert output.exists()
    assert result["size_bytes"] == output.stat().st_size > 0
    assert result["format"] == "pdf"


def test_extract_text_returns_the_document_text(soffice_server, docx_path):
    result = soffice_server.extract_text(str(docx_path))
    assert KNOWN_CONTENT in result["text"]
    assert result["char_count"] == len(result["text"])


def test_round_trip_docx_odt_text(soffice_server, docx_path):
    # PDF is excluded on purpose: LibreOffice imports PDFs as Draw, and the
    # encoded-text export filter cannot write those, so extract_text refuses
    # them by failing the conversion. Writer formats round-trip cleanly.
    odt = soffice_server.convert_document(str(docx_path), "odt")
    result = soffice_server.extract_text(odt["output_path"])
    assert KNOWN_CONTENT in result["text"]


def test_relative_paths_resolve_against_the_workdir(soffice_server, docx_path):
    result = soffice_server.extract_text("fixture.docx")
    assert KNOWN_CONTENT in result["text"]


def test_missing_source_is_reported(soffice_server):
    with pytest.raises(FileNotFoundError, match=r"missing\.docx"):
        soffice_server.convert_document("missing.docx", "pdf")
    with pytest.raises(FileNotFoundError):
        soffice_server.extract_text("missing.docx")


def test_unsupported_format_is_refused(soffice_server, docx_path):
    with pytest.raises(ValueError, match="Unsupported target format"):
        soffice_server.convert_document(str(docx_path), "exe")


def test_empty_path_is_refused(soffice_server):
    with pytest.raises(ValueError, match="path is empty"):
        soffice_server.extract_text("")
