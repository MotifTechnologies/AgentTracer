"""Run the actual reconciliation shell with a mocked GitHub CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("jq"),
    reason="Workflow regression tests require bash and jq (available in CI)",
)

MOCK_GH = """\
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
scenario = json.loads(Path(os.environ['SCENARIO_FILE']).read_text())
with open(os.environ['CALLS_FILE'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['pr', 'list']:
    print('41')
elif args[:2] == ['pr', 'checks']:
    assert '--required' in args
    sys.exit(scenario['checks_exit'])
elif args[:2] == ['api', 'graphql']:
    query = next(arg for arg in args if arg.startswith('query='))
    if 'enqueuePullRequest' in query:
        assert 'expectedHeadOid:$head' in query
        assert 'head=' + scenario['pr']['headRefOid'] in args
        assert 'id=' + scenario['pr']['id'] in args
        sys.exit(scenario['enqueue_exit'])
    print(json.dumps(scenario['pr']))
else:
    raise AssertionError(args)
"""


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "workflow_run"])
@pytest.mark.parametrize(
    ("merge_state", "review", "checks_exit", "enqueue_exit", "expected_calls"),
    [
        ("CLEAN", "APPROVED", 0, 0, ["checks", "enqueue"]),
        ("BEHIND", "APPROVED", 0, 0, ["checks", "enqueue"]),
        ("UNSTABLE", "APPROVED", 0, 0, ["checks", "enqueue"]),
        ("UNSTABLE", "APPROVED", 1, 0, ["checks"]),
        ("UNSTABLE", "APPROVED", 8, 0, ["checks"]),
        ("UNSTABLE", "APPROVED", 0, 1, ["checks", "enqueue"]),
        ("UNSTABLE", "REVIEW_REQUIRED", 0, 0, []),
        ("BLOCKED", "APPROVED", 0, 0, []),
    ],
)
def test_reconciliation_required_checks(
    tmp_path: Path,
    event: str,
    merge_state: str,
    review: str,
    checks_exit: int,
    enqueue_exit: int,
    expected_calls: list[str],
) -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/auto-merge.yml"
    ).read_text()
    # The reconciliation step is the final block in this workflow. Execute its
    # shell directly so these tests exercise the production jq gates and order.
    _, marker, body = workflow.partition("        run: |\n")
    assert marker, "Expected the inline reconciliation shell step"
    script = dedent(body)
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps(
            {
                "pr": {
                    "id": "PR_test",
                    "state": "OPEN",
                    "isDraft": False,
                    "baseRefName": "main",
                    "headRefOid": "a" * 40,
                    "autoMergeRequest": {"enabledAt": "2026-10-19"},
                    "reviewDecision": review,
                    "mergeStateStatus": merge_state,
                    "isMergeQueueEnabled": True,
                    "mergeQueueEntry": None,
                },
                "checks_exit": checks_exit,
                "enqueue_exit": enqueue_exit,
            }
        )
    )
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n{MOCK_GH}")
    gh.chmod(0o755)
    calls_file = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": str(tmp_path) + os.pathsep + os.defpath,
            "SCENARIO_FILE": str(scenario_file),
            "CALLS_FILE": str(calls_file),
            "GH_REPO": "example/repo",
            "EVENT_NAME": event,
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    checks_and_enqueues = []
    for call in calls:
        if call[:2] == ["pr", "checks"]:
            checks_and_enqueues.append("checks")
        elif any("enqueuePullRequest" in arg for arg in call):
            checks_and_enqueues.append("enqueue")
    assert checks_and_enqueues == expected_calls
    assert result.returncode == enqueue_exit, result.stdout + result.stderr
