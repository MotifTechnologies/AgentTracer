"""agent-tracer CLI."""

from __future__ import annotations

import asyncio
import sys

import click

from agent_tracer.config import ConfigError, load_config


@click.group()
def main() -> None:
    """agent-tracer: run agentic tasks and record structured trajectories."""


@main.command()
@click.option(
    "--config", "-f", "config_path", required=True, type=click.Path(exists=True)
)
@click.option(
    "--set",
    "-c",
    "overrides",
    multiple=True,
    help="Dotted config override, e.g. -c runner.max_concurrency=16",
)
def run(config_path: str, overrides: tuple[str, ...]) -> None:
    """Run tasks from the configured dataset and save trajectories."""
    try:
        config = load_config(config_path, list(overrides))
    except ConfigError as e:
        click.secho(f"config error: {e}", fg="red", err=True)
        sys.exit(2)

    from agent_tracer.run.runner import Runner

    try:
        results = asyncio.run(Runner(config).run())
    except ConfigError as e:
        # A run-fatal configuration problem surfaced only once a sandbox was
        # up — a shared image missing a server's binary. Same class of error
        # as a bad config file, reported the same way.
        click.secho(f"config error: {e}", fg="red", err=True)
        sys.exit(2)

    total = len(results)
    submitted = sum(1 for r in results if r["exit_status"] == "submitted")
    errors = sum(1 for r in results if r["exit_status"] == "error")
    correct = sum(1 for r in results if r.get("correct"))
    click.echo(
        f"done: {total} tasks | submitted {submitted} | errors {errors} | correct {correct} "
        f"| results: {config.output.path / 'results.jsonl'}"
    )
    if errors:
        sys.exit(1)


@main.command()
@click.option(
    "--trajectories",
    "-t",
    "trajectory_dir",
    default="results/trajectories",
    type=click.Path(exists=True, file_okay=False),
    show_default=True,
)
@click.option(
    "--format",
    "-F",
    "export_format",
    type=click.Choice(["sharegpt", "hf", "grpo"]),
    default="sharegpt",
    show_default=True,
    help="sharegpt: JSONL records | hf: HuggingFace Dataset dir | grpo: reward-annotated JSONL",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    default=None,
    help="Output path (default: results/dataset.jsonl, results/hf_dataset/, results/grpo.jsonl)",
)
@click.option("--name", default="agent-tracer", show_default=True, help="source.name")
@click.option("--split", default="train", show_default=True, help="source.split")
@click.option("--subset", default=None, help="source.subset")
@click.option("--category", default=None, help="record category")
@click.option(
    "--include-errors", is_flag=True, help="Also export error-status trajectories"
)
@click.option(
    "--require-correct",
    is_flag=True,
    help="Keep only rollouts whose recorded verdict is correct (aborts on ungraded ones)",
)
@click.option(
    "--best-per-task",
    is_flag=True,
    help="Rejection sampling: keep the shortest correct rollout per task, one record each",
)
def export(
    trajectory_dir: str,
    export_format: str,
    output_path: str | None,
    name: str,
    split: str,
    subset: str | None,
    category: str | None,
    include_errors: bool,
    require_correct: bool,
    best_per_task: bool,
) -> None:
    """Export trajectories to training formats (ShareGPT JSONL / HF Dataset / GRPO)."""
    from pathlib import Path

    from agent_tracer.export.sharegpt import UngradedTrajectoryError, load_records

    defaults = {
        "sharegpt": "results/dataset.jsonl",
        "hf": "results/hf_dataset",
        "grpo": "results/grpo.jsonl",
    }
    out = Path(output_path or defaults[export_format])

    try:
        records, skipped, stats = load_records(
            Path(trajectory_dir),
            name=name,
            split=split,
            subset=subset,
            category=category,
            include_errors=include_errors,
            require_correct=require_correct,
            best_per_task=best_per_task,
        )
    except UngradedTrajectoryError as e:
        click.secho(f"export error: {e}", fg="red", err=True)
        sys.exit(2)

    if export_format == "sharegpt":
        import json

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        written = len(records)
    elif export_format == "hf":
        from agent_tracer.export.formats import records_to_hf_dataset

        written = records_to_hf_dataset(records, out)
    else:
        from agent_tracer.export.formats import records_to_grpo_jsonl

        written = records_to_grpo_jsonl(records, out)

    detail = "".join(f", {k.replace('_', ' ')} {v}" for k, v in stats.items() if v)
    click.echo(
        f"exported {written} records ({export_format}) to {out} "
        f"(skipped {skipped} error trajectories{detail})"
    )


if __name__ == "__main__":
    main()
