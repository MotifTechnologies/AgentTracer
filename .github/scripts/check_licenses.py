"""Check CycloneDX declarations against repository policy, not legal compatibility."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from license_expression import ExpressionError, get_spdx_licensing

LICENSING = get_spdx_licensing()
# Preserve the existing permissive/weak-copyleft policy with exact identifiers.
# Notice/source obligations still require review for the actual distribution.
ACCEPTED = {
    "0BSD",
    "Apache-1.1",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSD-3-Clause-Clear",
    "CC0-1.0",
    "CNRI-Python",
    "HPND",
    "ISC",
    "LGPL-2.0-only",
    "LGPL-2.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "MPL-1.1",
    "MPL-2.0",
    "PSF-2.0",
    "Python-2.0",
    "PostgreSQL",
    "Unlicense",
    "Zlib",
}
# Exact legacy declarations, never substring matches. BSD classifiers identify
# a family rather than a variant; the report retains that distinction.
LEGACY = {
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "MIT License": "MIT",
    "The BSD 2-Clause License": "BSD-2-Clause",
    "PSF": "PSF-2.0",
    "PSFL": "PSF-2.0",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}
LEGACY_CATEGORIES = {"License :: OSI Approved :: BSD License"}

# python-dateutil's generic "Dual License" is resolved only when the exact
# distributed LICENSE inspected during this change accompanies the declaration.
# Its text applies BSD-3-Clause to all code, and Apache-2.0 to newer contributions.
# Source: https://github.com/dateutil/dateutil/blob/2.9.0.post0/LICENSE
REVIEWED_TEXTS = {
    ("python-dateutil", "2.9.0.post0", "Dual License"): (
        "ba00f51a0d92823b5a1cde27d8b5b9d2321e67ed8da9bc163eff96d5e17e577e",
        "BSD-3-Clause AND Apache-2.0",
    ),
}

REVIEWED_BUNDLES = [
    json.loads(path.read_text("utf-8"))
    for path in sorted((Path(__file__).parents[1] / "license-reviews").glob("*.json"))
]


def reviewed_bundle(component: dict, declared: str) -> dict | None:
    """Approve only the exact reviewed package, declaration and complete file set."""
    files = {}
    for choice in component.get("licenses", []):
        info = choice.get("license", {})
        prefix = "declared license file: "
        if not info.get("name", "").startswith(prefix):
            continue
        name = info["name"][len(prefix) :]
        if name in files:
            return None
        text = info.get("text", {})
        try:
            content = text.get("content", "").encode("utf-8")
            if text.get("encoding") == "base64":
                content = base64.b64decode(content, validate=True)
            elif text.get("encoding"):
                return None
        except (ValueError, UnicodeError):
            return None
        files[name] = hashlib.sha256(content).hexdigest()
    for review in REVIEWED_BUNDLES:
        if (
            (component["name"], component.get("version"), declared)
            == (review["name"], review["version"], review["declaration"])
            and files
            and files in review["file_sets"]
        ):
            return {"reference": review["reference"], "files_sha256": files}
    return None


def reviewed_expression(component: dict, declared: str) -> str:
    review = REVIEWED_TEXTS.get((component["name"], component.get("version"), declared))
    if review is None:
        return declared
    for choice in component.get("licenses", []):
        text = choice.get("license", {}).get("text", {})
        try:
            content = text.get("content", "").encode("utf-8")
            if text.get("encoding") == "base64":
                content = base64.b64decode(content, validate=True)
        except (ValueError, UnicodeError):
            continue
        if hashlib.sha256(content).hexdigest() == review[0]:
            return review[1]
    return declared


def expression_verdict(expression: str) -> str:
    """Respect SPDX AND/OR/WITH and reject unidentified/custom expressions."""
    if (
        not expression.strip()
        or "licenseref-" in expression.casefold()
        or "documentref-" in expression.casefold()
    ):
        return "unknown"
    try:
        parsed = LICENSING.parse(expression, validate=True, strict=True)
    except (ExpressionError, ValueError):
        return "unknown"
    if parsed is None:
        return "unknown"
    values = {
        symbol: LICENSING.TRUE if str(symbol) in ACCEPTED else LICENSING.FALSE
        for symbol in parsed.symbols
    }
    return "allowed" if parsed.subs(values).simplify() == LICENSING.TRUE else "blocked"


def component_verdict(component: dict) -> tuple[str, list[dict]]:
    """Check all declarations; full text attachments remain SBOM evidence.

    Multiple CycloneDX entries are not assumed to be OR alternatives.
    Legacy License metadata may appear as text in a generated entry.
    A full text attachment alone cannot be classified by this SPDX parser.
    """
    declarations = []
    for choice in component.get("licenses", []):
        if "expression" in choice:
            value = choice["expression"]
        else:
            license_info = choice.get("license", {})
            value = license_info.get("id") or license_info.get("name", "")
            generated = value == f"declared license of '{component['name']}'"
            attachment = value.startswith("declared license file: ")
            if generated:
                text = license_info.get("text", {})
                value = text.get("content", "")
                if text.get("encoding") == "base64":
                    try:
                        value = base64.b64decode(value, validate=True).decode("utf-8")
                    except (ValueError, UnicodeError):
                        value = ""
                if len(value) > 200 or "\n" in value.strip():
                    continue
            elif attachment:
                continue
        normalized = LEGACY.get(
            value.strip(), reviewed_expression(component, value.strip())
        )
        verdict = (
            "allowed" if value in LEGACY_CATEGORIES else expression_verdict(normalized)
        )
        review = reviewed_bundle(component, value.strip())
        if review is not None:
            verdict = "allowed"
        declaration = {"declared": value, "normalized": normalized, "verdict": verdict}
        if review is not None:
            declaration["review"] = review
        declarations.append(declaration)
    verdicts = {d["verdict"] for d in declarations}
    if "blocked" in verdicts:
        return "blocked", declarations
    if not declarations or "unknown" in verdicts:
        return "unknown", declarations
    return "allowed", declarations


def check_bom(bom: dict, source: str) -> list[dict]:
    if bom.get("bomFormat") != "CycloneDX" or not bom.get("components"):
        raise ValueError(f"{source}: expected a non-empty CycloneDX SBOM")
    components = list(bom["components"])
    root = bom.get("metadata", {}).get("component")
    if root and root.get("name"):
        components.append(root)
    rows = []
    for component in components:
        if not component.get("name") or not component.get("version"):
            raise ValueError(f"{source}: a component lacks its name/version")
        verdict, declarations = component_verdict(component)
        rows.append(
            {
                "sbom": source,
                "name": component["name"],
                "version": component["version"],
                "purl": component.get("purl"),
                "verdict": verdict,
                "declarations": declarations,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sboms", nargs="+", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows, errors = [], []
    for path in args.sboms:
        try:
            rows.extend(check_bom(json.loads(path.read_text("utf-8")), path.name))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{path.name}: {exc}")
    failed = [r for r in rows if r["verdict"] != "allowed"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "policy": "repository-license-policy-v1",
                "components": rows,
                "errors": errors,
                "passed": not (failed or errors),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for row in failed:
        print(
            f"{row['verdict'].upper()} {row['sbom']} {row['name']}=={row['version']}: {row['declarations']}"
        )
    for error in errors:
        print(f"ERROR {error}")
    print(
        f"{len(rows)} component checks; {len(failed)} need review; {len(errors)} SBOM errors."
    )
    return int(bool(failed or errors))


if __name__ == "__main__":
    raise SystemExit(main())
