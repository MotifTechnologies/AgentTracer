import json
from pathlib import Path

import pytest

from agent_tracer.config.schema import ConfigError
from agent_tracer.datasets.swebench_local import SWEBenchLocalDataset

GOLD = """diff --git a/src/mod.py b/src/mod.py
index 111..222 100644
--- a/src/mod.py
+++ b/src/mod.py
@@ -1,3 +1,3 @@
-def f(x):
-    return x + 1
+def f(x):
+    return x + 2
"""


class TestSWEBenchLocalDataset:
    def _write(self, tmp_path: Path, **overrides) -> Path:
        row = {
            "repo": "org/repo",
            "instance_id": "org__repo-1",
            "base_commit": "abc123",
            "problem_statement": "fix the off-by-one",
            "patch": GOLD,
        }
        row.update(overrides)
        path = tmp_path / "crawled.jsonl"
        path.write_text(json.dumps(row) + "\n")
        return path

    def test_load_maps_fields(self, tmp_path):
        task = SWEBenchLocalDataset(self._write(tmp_path)).load()[0]
        assert task.task_id == "org__repo-1"
        assert "org/repo" in task.input and "abc123" in task.input
        assert task.reference == GOLD
        assert task.metadata["repo"] == "org/repo"

    def test_missing_keys_fail_fast(self, tmp_path):
        path = self._write(tmp_path, patch="")
        with pytest.raises(ConfigError, match="missing keys"):
            SWEBenchLocalDataset(path).load()

    def test_evaluate_never_claims_a_verdict(self, tmp_path):
        """Correctness needs a task-specific verifier — out of scope here."""
        dataset = SWEBenchLocalDataset(self._write(tmp_path))
        task = dataset.load()[0]
        for submission in (GOLD, "unrelated diff", None):
            result = dataset.evaluate(task, submission)
            assert result.correct is None
            assert result.score is None

    def test_limit(self, tmp_path):
        path = tmp_path / "many.jsonl"
        rows = [
            {
                "repo": "org/repo",
                "instance_id": f"org__repo-{i}",
                "base_commit": "abc123",
                "problem_statement": "fix it",
                "patch": GOLD,
            }
            for i in range(5)
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        assert len(SWEBenchLocalDataset(path).load(limit=2)) == 2
