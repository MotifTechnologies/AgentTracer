import json

import pytest

from agent_tracer.config.schema import ConfigError
from agent_tracer.datasets.bfcl_fixture import BFCLFixtureDataset
from agent_tracer.datasets.custom import CustomDataset
from agent_tracer.datasets.swebench_local import SWEBenchLocalDataset

LOADERS = [CustomDataset, SWEBenchLocalDataset, BFCLFixtureDataset]


def _row(loader, content="test"):
    if loader is CustomDataset:
        return {"task_id": "t1", "input": content}
    if loader is SWEBenchLocalDataset:
        return {
            "repo": "org/repo",
            "instance_id": "t1",
            "base_commit": "abc",
            "problem_statement": content,
            "patch": "diff",
        }
    return {
        "task_id": "t1",
        "category": "test",
        "tools": [],
        "initial_state": {},
        "user_turns": [{"content": content, "expected_state": {}}],
        "provenance": {},
    }


@pytest.mark.parametrize("loader", LOADERS)
@pytest.mark.parametrize("row", ["task_id input", [], 42, True, None])
def test_non_object_rows_report_path_and_physical_line(tmp_path, loader, row):
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        loader(path).load()
    assert f"{path}:2" in str(error.value)
    assert "must be a JSON object" in str(error.value)


@pytest.mark.parametrize("loader", LOADERS)
@pytest.mark.parametrize("directory", [False, True])
def test_missing_dataset_is_a_config_error(tmp_path, loader, directory):
    path = tmp_path / "tasks.jsonl"
    if directory:
        path.mkdir()
    with pytest.raises(ConfigError, match="not found") as error:
        loader(path).load()
    assert str(path) in str(error.value)


@pytest.mark.parametrize("loader", LOADERS)
def test_invalid_json_reports_path_and_physical_line(tmp_path, loader):
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps(_row(loader)) + "\n\n{broken\n", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        loader(path).load()
    assert f"{path}:3" in str(error.value)
    assert "invalid JSON" in str(error.value)


@pytest.mark.parametrize("loader", LOADERS)
@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_unicode_separators_are_preserved_inside_json_strings(
    tmp_path, loader, separator
):
    path = tmp_path / "tasks.jsonl"
    content = f"first{separator}second"
    path.write_text(
        json.dumps(_row(loader, content), ensure_ascii=False) + "\n\n{broken\n",
        encoding="utf-8",
    )
    tasks = loader(path).load(limit=1)
    assert len(tasks) == 1
    assert content in tasks[0].input
    with pytest.raises(ConfigError) as error:
        loader(path).load()
    assert f"{path}:3" in str(error.value)


def test_fixture_schema_error_reports_path_and_line(tmp_path):
    path = tmp_path / "fixtures.jsonl"
    path.write_text("\n{}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        BFCLFixtureDataset(path).load()
    assert f"{path}:2" in str(error.value)
    assert "invalid fixture" in str(error.value)


def test_duplicate_fixture_reports_the_offending_line(tmp_path):
    path = tmp_path / "fixtures.jsonl"
    row = json.dumps(_row(BFCLFixtureDataset))
    path.write_text(row + "\n\n" + row + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate fixture task identity") as error:
        BFCLFixtureDataset(path).load()
    assert f"{path}:3" in str(error.value)
