# /// script
# requires-python = ">=3.11"
# dependencies = ["datasets>=3"]
# ///
"""Build a coding-domain seed pool from SWE-rebench.

Standalone data-prep tooling — deliberately kept outside the agent-tracer
package, which is about *running* agents, not curating source corpora.

Filters applied, in order:

1. **Verifiability** — keep only rows with a prebuilt Docker image and a
   non-empty FAIL_TO_PASS list, so every seed can be graded by test execution.
2. **License** — keep permissive licenses only. Unknown (null) licenses, weak
   copyleft (MPL), and the BSD-4-Clause advertising clause are dropped: the
   generated dataset is published under Apache 2.0 and every row carries
   derived repo content, so provenance must be clean and attributable.
3. **Eval decontamination** — drop repos that appear in SWE-bench
   Verified/Lite, which stay reserved as the held-out evaluation benchmark.
4. **Diversity cap** — at most N seeds per repo, so a handful of large repos
   cannot dominate the trajectory distribution.

Outputs a JSONL consumable by ``agent_tracer.datasets.swebench_local`` plus a
manifest recording per-license / per-repo counts for compliance reporting.

    uv run DATA_BUILDER/build_swerebench_seeds.py --limit 600 --per-repo 5
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DATASET = "nebius/SWE-rebench"
SPLIT = "filtered"  # the split where every row ships a prebuilt Docker image

# Benchmarks held out for evaluation; their repos must not seed training data.
EVAL_BENCHMARKS = [
    ("princeton-nlp/SWE-bench_Verified", "test"),
    ("princeton-nlp/SWE-bench_Lite", "test"),
]

# Permissive families, matched case-insensitively against license_name.
PERMISSIVE_PATTERNS = (
    r"\bmit\b",
    r"\bexpat\b",
    r"\bapache\b",
    r"\bbsd\b",
    r"\bisc\b",
    r"\bunlicense\b",
    r"\bcc0\b",
    r"creative commons zero",
    r"\bzope\b",
    r"\bpostgresql\b",
    r"academic free license",
)

# Explicit denials that would otherwise match a permissive pattern above, or
# that impose obligations incompatible with clean Apache 2.0 redistribution.
DENY_PATTERNS = (
    r"\bgpl\b",
    r"\blgpl\b",
    r"affero",
    r"mozilla public",
    r"\bmpl\b",
    r"eclipse public",
    r"\beupl\b",
    r"cecill",
    r"bsd 4-clause",  # advertising clause
    r"bsd-4-clause",
)


def classify_license(name: str | None) -> tuple[bool, str]:
    """Return (is_permissive, reason)."""
    if not name or not str(name).strip():
        return False, "unknown"
    text = str(name).lower()
    for pattern in DENY_PATTERNS:
        if re.search(pattern, text):
            return False, f"denied:{pattern}"
    for pattern in PERMISSIVE_PATTERNS:
        if re.search(pattern, text):
            return True, "permissive"
    return False, "unrecognized"


def eval_repos() -> set[str]:
    from datasets import load_dataset

    repos: set[str] = set()
    for name, split in EVAL_BENCHMARKS:
        repos |= set(load_dataset(name, split=split, columns=["repo"])["repo"])
    return repos


def to_seed_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map a SWE-rebench row onto the swebench_local seed schema."""
    return {
        # Fields required by agent_tracer.datasets.swebench_local
        "repo": row["repo"],
        "instance_id": row["instance_id"],
        "base_commit": row["base_commit"],
        "problem_statement": row["problem_statement"],
        "patch": row["patch"],
        "test_patch": row.get("test_patch"),
        "hints_text": row.get("hints_text"),
        "created_at": str(row.get("created_at")),
        # Provenance / compliance — carried into the published dataset
        "source_dataset": DATASET,
        "license_name": row.get("license_name"),
        # Execution-based verification (tier 3)
        "docker_image": row.get("docker_image"),
        "fail_to_pass": row.get("FAIL_TO_PASS"),
        "pass_to_pass": row.get("PASS_TO_PASS"),
        "install_config": row.get("install_config"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=600, help="max seeds to emit")
    parser.add_argument("--per-repo", type=int, default=5, help="max seeds per repo")
    parser.add_argument(
        "--min-year", type=int, default=None, help="keep only issues created on/after this year"
    )
    parser.add_argument("--out", type=Path, default=Path("data/seeds/swerebench_coding.jsonl"))
    parser.add_argument("--manifest", type=Path, default=None, help="default: <out>.manifest.json")
    args = parser.parse_args()

    from datasets import load_dataset

    print(f"loading {DATASET}[{SPLIT}] ...")
    ds = load_dataset(DATASET, split=SPLIT)
    held_out = eval_repos()
    print(f"held-out eval repos: {len(held_out)}")

    dropped = Counter()
    per_repo: defaultdict[str, int] = defaultdict(int)
    kept: list[dict[str, Any]] = []

    # Newest first: recent issues are least likely to be memorized by the
    # teacher model, so they yield more genuine debugging trajectories.
    order = sorted(range(len(ds)), key=lambda i: str(ds[i]["created_at"]), reverse=True)

    for i in order:
        if len(kept) >= args.limit:
            break
        row = ds[i]

        if not row.get("docker_image"):
            dropped["no_docker_image"] += 1
            continue
        if not row.get("FAIL_TO_PASS"):
            dropped["no_fail_to_pass"] += 1
            continue

        permissive, reason = classify_license(row.get("license_name"))
        if not permissive:
            dropped[f"license_{reason}"] += 1
            continue

        if row["repo"] in held_out:
            dropped["eval_repo_overlap"] += 1
            continue

        if args.min_year and str(row.get("created_at", ""))[:4] < str(args.min_year):
            dropped["too_old"] += 1
            continue

        if per_repo[row["repo"]] >= args.per_repo:
            dropped["per_repo_cap"] += 1
            continue

        per_repo[row["repo"]] += 1
        kept.append(to_seed_row(row))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for seed in kept:
            f.write(json.dumps(seed, ensure_ascii=False) + "\n")

    licenses = Counter(s["license_name"] for s in kept)
    manifest = {
        "source_dataset": DATASET,
        "source_split": SPLIT,
        "source_rows": len(ds),
        "seeds": len(kept),
        "repos": len(per_repo),
        "filters": {
            "per_repo_cap": args.per_repo,
            "min_year": args.min_year,
            "held_out_eval_repos": sorted(held_out),
        },
        "dropped": dict(dropped),
        "licenses": dict(licenses),
        "top_repos": dict(Counter(per_repo).most_common(20)),
        "created_at_range": [
            min(s["created_at"] for s in kept),
            max(s["created_at"] for s in kept),
        ]
        if kept
        else None,
    }
    manifest_path = args.manifest or args.out.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nwrote {len(kept)} seeds from {len(per_repo)} repos -> {args.out}")
    print(f"manifest -> {manifest_path}")
    print("\ndropped:")
    for reason, count in dropped.most_common():
        print(f"  {count:6d}  {reason}")
    print("\nlicenses:")
    for name, count in licenses.most_common(10):
        print(f"  {count:5d}  {name}")


if __name__ == "__main__":
    main()
