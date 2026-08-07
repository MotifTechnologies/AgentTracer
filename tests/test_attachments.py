import pytest

from agent_tracer.core.task import Task
from agent_tracer.orchestrators.single import _materialized_attachments


def _task(files=None):
    return Task(
        task_id="t1",
        input="do it",
        attachments={"files": files} if files is not None else None,
    )


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
        with pytest.raises(ValueError, match="escapes workspace"):
            with _materialized_attachments(_task({"../evil.txt": "x"})):
                pass

    def test_cleanup_on_error(self):
        saved = {}

        def _capture():
            with _materialized_attachments(_task({"ok.txt": "x", "../bad": "y"})) as ws:
                saved["path"] = ws

        with pytest.raises(ValueError):
            _capture()
        assert not saved.get("path")
