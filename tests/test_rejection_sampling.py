import pytest

from agent_tracer.export.sharegpt import UngradedTrajectoryError, select_records


def _record(task, sample_idx, correct, steps=5, tokens=1000):
    return {
        "extra": {
            "task": task,
            "sample_idx": sample_idx,
            "steps": steps,
            "usage": {"total_tokens": tokens},
            "evaluation": None if correct is None else {"correct": correct, "score": None},
        }
    }


class TestRequireCorrect:
    def test_incorrect_rollouts_dropped(self):
        records = [_record("t1", 0, True), _record("t1", 1, False)]
        kept, stats = select_records(records, require_correct=True)
        assert [r["extra"]["sample_idx"] for r in kept] == [0]
        assert stats["dropped_incorrect"] == 1

    def test_all_samples_kept_when_all_correct(self):
        records = [_record("t1", i, True) for i in range(4)]
        kept, _ = select_records(records, require_correct=True)
        assert len(kept) == 4


class TestBestPerTask:
    def test_one_record_per_task(self):
        records = [_record("t1", i, True) for i in range(4)] + [_record("t2", 0, True)]
        kept, stats = select_records(records, best_per_task=True)
        assert len(kept) == 2
        assert sorted(r["extra"]["task"] for r in kept) == ["t1", "t2"]
        assert stats["dropped_extra_samples"] == 3

    def test_shortest_correct_rollout_wins(self):
        records = [
            _record("t1", 0, True, steps=9),
            _record("t1", 1, False, steps=2),  # shorter but wrong
            _record("t1", 2, True, steps=4),
        ]
        kept, _ = select_records(records, best_per_task=True)
        assert [r["extra"]["sample_idx"] for r in kept] == [2]

    def test_tokens_break_a_step_tie(self):
        records = [
            _record("t1", 0, True, steps=5, tokens=9000),
            _record("t1", 1, True, steps=5, tokens=3000),
        ]
        kept, _ = select_records(records, best_per_task=True)
        assert [r["extra"]["sample_idx"] for r in kept] == [1]

    def test_task_with_no_correct_rollout_is_dropped_and_counted(self):
        records = [_record("t1", 0, False), _record("t1", 1, False), _record("t2", 0, True)]
        kept, stats = select_records(records, best_per_task=True)
        assert [r["extra"]["task"] for r in kept] == ["t2"]
        assert stats["tasks_without_a_correct_sample"] == 1


class TestUngradedAborts:
    @pytest.mark.parametrize("flags", [{"require_correct": True}, {"best_per_task": True}])
    def test_missing_verdict_raises(self, flags):
        records = [_record("t1", 0, True), _record("t1", 1, None)]
        with pytest.raises(UngradedTrajectoryError, match="no correctness verdict"):
            select_records(records, **flags)

    def test_ungraded_passes_through_without_the_flags(self):
        records = [_record("t1", 0, None)]
        kept, stats = select_records(records)
        assert kept == records
        assert stats == {}
