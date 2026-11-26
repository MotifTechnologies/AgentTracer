import json

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


@pytest.mark.parametrize(
    "first_id, duplicate_id", [("a", "a"), (7, "7"), (None, "None")]
)
def test_duplicate_custom_ids_report_the_offending_line(
    tmp_path, first_id, duplicate_id
):
    path = _write(
        tmp_path,
        [
            json.dumps({"task_id": first_id, "input": "first"}),
            "",
            json.dumps({"task_id": duplicate_id, "input": "second"}),
        ],
    )
    with pytest.raises(ConfigError, match="duplicate task_id") as error:
        CustomDataset(path).load()
    assert f"{path}:3" in str(error.value)
    assert repr(str(duplicate_id)) in str(error.value)


def test_custom_limit_does_not_read_duplicate_beyond_prefix(tmp_path):
    path = _write(
        tmp_path,
        [
            '{"task_id": "a", "input": "first"}',
            '{"task_id": "a", "input": "second"}',
        ],
    )
    assert [task.input for task in CustomDataset(path).load(limit=1)] == ["first"]
    with pytest.raises(ConfigError, match="duplicate task_id"):
        CustomDataset(path).load(limit=2)


def test_custom_unique_ids_can_be_loaded_again(tmp_path):
    path = _write(
        tmp_path,
        [
            '{"task_id": "a", "input": "first"}',
            '{"task_id": "b", "input": "second"}',
        ],
    )
    dataset = CustomDataset(path)
    for _ in range(2):
        assert [task.task_id for task in dataset.load()] == ["a", "b"]
