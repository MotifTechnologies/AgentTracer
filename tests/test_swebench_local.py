import json
from pathlib import Path

import pytest

from agent_tracer.config.schema import ConfigError
from agent_tracer.datasets.swebench_local import SWEBenchLocalDataset
from agent_tracer.eval.patch_similarity import compare_patches, touched_files

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

DIFFERENT = """diff --git a/src/other.py b/src/other.py
index 111..222 100644
--- a/src/other.py
+++ b/src/other.py
@@ -1,2 +1,2 @@
-y = 1
+y = 2
"""


class TestPatchSimilarity:
    def test_touched_files(self):
        assert touched_files(GOLD) == {"src/mod.py"}

    def test_identical_patch_scores_one(self):
        sim = compare_patches(GOLD, GOLD)
        assert sim.files_match == 1.0
        assert sim.added_sim == 1.0
        assert sim.score == 1.0

    def test_different_file_gates_score_to_zero(self):
        sim = compare_patches(DIFFERENT, GOLD)
        assert sim.files_match == 0.0
        assert sim.score == 0.0

    def test_empty_submission(self):
        sim = compare_patches("", GOLD)
        assert sim.score == 0.0


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

    def test_evaluate_tiers(self, tmp_path):
        dataset = SWEBenchLocalDataset(self._write(tmp_path))
        task = dataset.load()[0]
        assert dataset.evaluate(task, GOLD).correct is True
        assert dataset.evaluate(task, DIFFERENT).correct is False
        assert dataset.evaluate(task, None).correct is None
        result = dataset.evaluate(task, GOLD)
        assert result.details["tier"] == 1

    def test_real_seed_sample_loads(self):
        seeds = Path("data/seeds/swebench_local_sample.jsonl")
        tasks = SWEBenchLocalDataset(seeds).load()
        assert len(tasks) == 5
        assert all(t.reference for t in tasks)
