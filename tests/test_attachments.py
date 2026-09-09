import base64

import pytest

from agent_tracer.core.task import Task
from agent_tracer.orchestrators.single import _materialized_attachments


def _task(files=None, files_b64=None):
    attachments = {}
    if files is not None:
        attachments["files"] = files
    if files_b64 is not None:
        attachments["files_b64"] = files_b64
    return Task(task_id="t1", input="do it", attachments=attachments or None)


class TestBinaryAttachments:
    def test_bytes_round_trip_exactly(self):
        raw = bytes(range(256))
        encoded = base64.b64encode(raw).decode()
        with _materialized_attachments(
            _task(files_b64={"data/db.sqlite": encoded})
        ) as ws:
            assert (ws / "data/db.sqlite").read_bytes() == raw

    def test_text_and_binary_together(self):
        encoded = base64.b64encode(b"\x89PNG\r\n").decode()
        task = _task(files={"notes.md": "hi\n"}, files_b64={"img/logo.png": encoded})
        with _materialized_attachments(task) as ws:
            assert (ws / "notes.md").read_text() == "hi\n"
            assert (ws / "img/logo.png").read_bytes() == b"\x89PNG\r\n"

    def test_invalid_base64_is_rejected(self):
        with (
            pytest.raises(ValueError, match="invalid base64"),
            _materialized_attachments(_task(files_b64={"x.bin": "not base64!!"})),
        ):
            pass

    def test_same_path_as_text_and_binary_is_rejected(self):
        task = _task(
            files={"a.bin": "x"}, files_b64={"a.bin": base64.b64encode(b"y").decode()}
        )
        with (
            pytest.raises(ValueError, match="both text and binary"),
            _materialized_attachments(task),
        ):
            pass

    def test_binary_path_escape_rejected(self):
        encoded = base64.b64encode(b"x").decode()
        with (
            pytest.raises(ValueError, match="escapes workspace"),
            _materialized_attachments(_task(files_b64={"../evil.bin": encoded})),
        ):
            pass


class TestMaterializedAttachments:
    def test_no_attachments_yields_none(self):
        with _materialized_attachments(_task()) as workspace:
            assert workspace is None

    def test_empty_files_yields_none(self):
        with _materialized_attachments(_task({})) as workspace:
            assert workspace is None

    def test_nested_paths_preserved(self):
        files = {"logs/access.log": "GET /\n", "config/settings.ini": "[a]\nb = 1\n"}
        with _materialized_attachments(_task(files)) as workspace:
            assert (workspace / "logs/access.log").read_text() == "GET /\n"
            assert (workspace / "config/settings.ini").read_text().startswith("[a]")

    def test_cleaned_up_after_use(self):
        with _materialized_attachments(_task({"a.txt": "x"})) as workspace:
            saved = workspace
            assert saved.exists()
        assert not saved.exists()

    def test_path_escape_rejected(self):
        with (
            pytest.raises(ValueError, match="escapes workspace"),
            _materialized_attachments(_task({"../evil.txt": "x"})),
        ):
            pass

    def test_cleanup_on_error(self):
        saved = {}

        def _capture():
            with _materialized_attachments(_task({"ok.txt": "x", "../bad": "y"})) as ws:
                saved["path"] = ws

        with pytest.raises(ValueError):
            _capture()
        assert not saved.get("path")
