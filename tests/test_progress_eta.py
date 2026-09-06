from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)

from agent_tracer.run.runner import Runner


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _bar(period: float) -> Progress:
    return Progress(
        TextColumn("t"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        disable=True,
        speed_estimate_period=period,
        get_time=_CLOCK,
    )


_CLOCK = _Clock()


class TestEtaSurvivesSlowTasks:
    """rich estimates speed over a window; advances further apart than the
    window leave one sample, zero elapsed, and no ETA for the whole run."""

    def _run(self, period: float, gap: float):
        _CLOCK.t = 1000.0
        progress = _bar(period)
        task_id = progress.add_task("run", total=200)
        progress.start_task(task_id)
        for _ in range(3):
            _CLOCK.t += gap
            progress.advance(task_id)
        return progress.tasks[0]

    def test_default_window_loses_the_eta_on_minutes_long_tasks(self):
        assert self._run(30.0, gap=300).time_remaining is None

    def test_runners_window_keeps_it(self):
        task = self._run(3600.0, gap=300)
        assert task.time_remaining is not None
        assert task.speed > 0

    def test_the_runner_asks_for_the_wider_window(self):
        import inspect

        source = inspect.getsource(Runner.run)
        assert "speed_estimate_period=3600" in source
