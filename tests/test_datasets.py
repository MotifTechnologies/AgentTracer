import pytest

from agent_tracer.config.schema import ConfigError
from agent_tracer.datasets.custom import CustomDataset


def _write(tmp_path, lines):
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


class TestCustomDataset:
    def test_load_and_limit(self, tmp_path):
        path = _write(
            tmp_path,
            [
                '{"task_id": "a", "input": "x", "reference": "1"}',
                '{"task_id": "b", "input": "y"}',
                '{"task_id": "c", "input": "z"}',
            ],
        )
        tasks = CustomDataset(path).load(limit=2)
        assert [t.task_id for t in tasks] == ["a", "b"]

    def test_invalid_json_fails_fast(self, tmp_path):
        path = _write(tmp_path, ['{"task_id": "a", "input": "x"}', "{oops"])
        with pytest.raises(ConfigError, match="invalid JSON"):
            CustomDataset(path).load()

    def test_missing_fields_fail_fast(self, tmp_path):
        path = _write(tmp_path, ['{"task_id": "a"}'])
        with pytest.raises(ConfigError, match="requires task_id and input"):
            CustomDataset(path).load()

    def test_evaluate_exact_match(self, tmp_path):
        path = _write(tmp_path, ['{"task_id": "a", "input": "x", "reference": "42"}'])
        dataset = CustomDataset(path)
        task = dataset.load()[0]
        assert dataset.evaluate(task, " 42 ").correct is True
        assert dataset.evaluate(task, "41").correct is False
        assert dataset.evaluate(task, None).correct is None
