"""Build Python runtime/development/MCP SBOMs without starting any MCP server."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*command: str, env: dict | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def python_in(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def mcp_scripts(root: Path) -> tuple[list[Path], list[dict]]:
    scripts, external = [], []
    for manifest in sorted((root / "src/agent_tracer/mcp_servers").glob("*/mcp.json")):
        data = json.loads(manifest.read_text("utf-8"))
        if data["transport"] == "http":
            external.append({"name": data["name"], "reason": "external HTTP service"})
            continue
        if data["command"] != "uv" or data["args"] != ["run", "--quiet", "server.py"]:
            raise ValueError(
                f"{manifest}: unsupported launch command; add explicit SBOM coverage"
            )
        script = manifest.parent / "server.py"
        if not script.is_file() or not script.with_suffix(".py.lock").is_file():
            raise ValueError(
                f"{script}: missing script or lockfile; run uv lock --script"
            )
        scripts.append(script)
    if not scripts:
        raise ValueError("No packaged MCP scripts found")
    return scripts, external


def generate(scope: str, target: Path, output: Path, *, project: bool = False) -> dict:
    path = output / f"{scope}.cdx.json"
    command = [
        sys.executable,
        "-m",
        "cyclonedx_py",
        "environment",
        str(python_in(target)),
        "--gather-license-texts",
        "--spec-version",
        "1.6",
        "--output-format",
        "JSON",
        "--output-file",
        str(path),
    ]
    if project:
        command.extend(["--pyproject", str(ROOT / "pyproject.toml")])
    run(*command)
    return {
        "scope": scope,
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sbom")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scripts, external = mcp_scripts(ROOT)
    index = {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "python": sys.version,
        "cyclonedx-bom": importlib.metadata.version("cyclonedx-bom"),
        "uv": subprocess.check_output([args.uv, "--version"], text=True).strip(),
        "inputs": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [
                ROOT / "pyproject.toml",
                Path(__file__),
                ROOT / ".github/scripts/check_licenses.py",
                *scripts,
            ]
        },
        "external": external,
        "sboms": [],
        "complete": False,
    }
    try:
        for scope, flags in (("runtime", ["--no-dev"]), ("development", ["--dev"])):
            target = output / "environments" / scope
            env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(target))
            run(
                args.uv, "sync", "--locked", "--no-group", "compliance", *flags, env=env
            )
            index["sboms"].append(generate(scope, target, output, project=True))
        for script in scripts:
            scope = f"mcp-{script.parent.name}"
            target = output / "environments" / scope
            requirements = output / f"{scope}.requirements.txt"
            run(
                args.uv,
                "export",
                "--script",
                str(script),
                "--locked",
                "--no-hashes",
                "-o",
                str(requirements),
            )
            if not python_in(target).is_file():
                run(args.uv, "venv", "--python", sys.executable, str(target))
            run(
                args.uv,
                "pip",
                "sync",
                "--python",
                str(python_in(target)),
                str(requirements),
            )
            entry = generate(scope, target, output)
            entry["script"] = script.relative_to(ROOT).as_posix()
            entry["lock_sha256"] = hashlib.sha256(
                script.with_suffix(".py.lock").read_bytes()
            ).hexdigest()
            index["sboms"].append(entry)
        index["complete"] = True
    finally:
        index["project_lock_sha256"] = hashlib.sha256(
            (ROOT / "uv.lock").read_bytes()
        ).hexdigest()
        (output / "index.json").write_text(
            json.dumps(index, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
