import json

from agent_tracer.export.formats import record_to_grpo_row, records_to_grpo_jsonl, records_to_hf_dataset
from agent_tracer.export.sharegpt import trajectory_to_record

from test_export import _traj


def _records():
    return [trajectory_to_record(_traj(), category="agent")]


class TestGRPO:
    def test_prompt_completion_split(self):
        row = record_to_grpo_row(_records()[0])
        assert [m["role"] for m in row["prompt"]] == ["system", "user"]
        assert [m["role"] for m in row["completion"]] == ["assistant", "tool"]
        assert row["reward"] == 1.0
        assert row["group_id"] == "t1"

    def test_reward_falls_back_to_correctness(self):
        record = _records()[0]
        record["extra"]["evaluation"] = {"correct": False, "score": None}
        assert record_to_grpo_row(record)["reward"] == 0.0

    def test_unevaluated_reward_is_none(self):
        record = _records()[0]
        record["extra"]["evaluation"] = None
        assert record_to_grpo_row(record)["reward"] is None

    def test_jsonl_roundtrip(self, tmp_path):
        out = tmp_path / "grpo.jsonl"
        assert records_to_grpo_jsonl(_records(), out) == 1
        row = json.loads(out.read_text().splitlines()[0])
        assert row["group_id"] == "t1"


class TestHFDataset:
    def test_save_and_reload(self, tmp_path):
        out = tmp_path / "hf"
        assert records_to_hf_dataset(_records(), out) == 1

        from datasets import load_from_disk

        dataset = load_from_disk(str(out))
        assert dataset.num_rows == 1
        row = dataset[0]
        assert row["source"]["provider"] is None
        assert [m["role"] for m in row["conversations"]] == ["system", "user", "assistant", "tool"]
