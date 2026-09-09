import json

from agent_tracer.core.trajectory import Trajectory


class TestSampleIndexedTrajectories:
    def test_sample_zero_keeps_the_plain_filename(self, tmp_path):
        path = Trajectory(task_id="t1").save(tmp_path)
        assert path.name == "t1.traj.json"

    def test_samples_do_not_overwrite_each_other(self, tmp_path):
        paths = {
            Trajectory(task_id="t1", sample_idx=i).save(tmp_path) for i in range(3)
        }
        assert len(paths) == 3
        assert len(list(tmp_path.glob("*.traj.json"))) == 3

    def test_sample_idx_is_recorded(self, tmp_path):
        path = Trajectory(task_id="t1", sample_idx=2).save(tmp_path)
        assert json.loads(path.read_text())["sample_idx"] == 2


class TestCheckpointKeyedOnSample:
    def _runner(self, tmp_path, rows, samples):
        from agent_tracer.config.schema import (
            DatasetConfig,
            ModelConfig,
            OutputConfig,
            RunConfig,
            RunnerConfig,
        )
        from agent_tracer.run.runner import Runner

        tasks = tmp_path / "t.jsonl"
        tasks.write_text('{"task_id": "t1", "input": "x"}\n')
        results = tmp_path / "out" / "results.jsonl"
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text("".join(json.dumps(r) + "\n" for r in rows))

        config = RunConfig(
            dataset=DatasetConfig(name="custom", path=tasks),
            model=ModelConfig(
                model_name="m",
                base_url="http://x/v1",
                api_key="k",
                reasoning_key="none",
            ),
            runner=RunnerConfig(samples_per_task=samples),
            output=OutputConfig(path=tmp_path / "out"),
        )
        return Runner(config)

    def test_a_finished_sample_is_skipped_but_its_siblings_are_not(self, tmp_path):
        runner = self._runner(
            tmp_path,
            [{"task_id": "t1", "sample_idx": 0, "exit_status": "submitted"}],
            samples=3,
        )
        assert runner._completed_samples() == {("t1", 0)}

    def test_errors_are_retried(self, tmp_path):
        runner = self._runner(
            tmp_path,
            [{"task_id": "t1", "sample_idx": 1, "exit_status": "error"}],
            samples=2,
        )
        assert runner._completed_samples() == set()

    def test_rows_without_sample_idx_read_as_sample_zero(self, tmp_path):
        """Results written before sampling existed must still resume."""
        runner = self._runner(
            tmp_path, [{"task_id": "t1", "exit_status": "submitted"}], samples=2
        )
        assert runner._completed_samples() == {("t1", 0)}
