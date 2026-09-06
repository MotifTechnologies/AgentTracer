"""Fail when a dependency's licence is incompatible with Apache-2.0.

Run as `uv run python .github/scripts/check_licenses.py`, against whatever is
installed in the environment.

The naive check — grep the licence string for "GPL" — is wrong here. Metadata
carries SPDX expressions, and `tld` ships "MPL-1.1 OR GPL-2.0-only OR
LGPL-2.1-or-later": an OR is the *licensee's* choice, so a package offering one
acceptable option is acceptable. AND means every term must hold. So the string
is parsed, not searched.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404
import sys

# Permissive, or weak copyleft that attaches to the dependency's own files and
# not to ours. Matched case-insensitively as substrings of one SPDX term.
ACCEPTED = (
    "mit", "bsd", "apache", "isc", "python software foundation", "psf",
    "zlib", "cc0", "unlicense", "public domain", "mpl", "mozilla public",
    "lgpl", "cnri", "0bsd", "postgresql", "hpnd", "ufl",
)

# Strong copyleft: linking our Apache-2.0 work against it would relicense us.
REJECTED = ("agpl", "sspl", "gpl-2.0", "gpl-3.0", "gplv2", "gplv3", "commons clause")

# Packages a human looked at and cleared, with the reason. Anything not here
# and not classifiable stops the build until someone decides.
EXCEPTIONS: dict[str, str] = {}


def _terms(expression: str) -> list[list[str]]:
    """SPDX expression -> OR-groups of AND-terms."""
    return [
        [t.strip() for t in re.split(r"\bAND\b", group, flags=re.I) if t.strip()]
        for group in re.split(r"\bOR\b|;", expression)
    ]


def _ok(term: str) -> bool | None:
    low = term.lower()
    if any(bad in low for bad in REJECTED):
        # "lgpl-2.1" contains "gpl-2.0"? No — but be explicit about Lesser.
        return False if "lgpl" not in low else True
    if any(good in low for good in ACCEPTED):
        return True
    return None  # unrecognised


def main() -> int:
    raw = subprocess.run(  # nosec B603
        [sys.executable, "-m", "piplicenses", "--format=json", "--with-urls"],
        capture_output=True, text=True, check=True,
    ).stdout
    blocked, unknown = [], []
    for pkg in json.loads(raw):
        name, lic = pkg["Name"], pkg["License"]
        if name in EXCEPTIONS or name in ("agent-tracer",):
            continue
        verdicts = [[_ok(t) for t in group] for group in _terms(lic)]
        # One OR-group all of whose AND-terms are acceptable is enough.
        if any(all(v is True for v in group) for group in verdicts):
            continue
        if any(v is None for group in verdicts for v in group):
            unknown.append((name, lic))
        else:
            blocked.append((name, lic))

    for name, lic in blocked:
        print(f"BLOCKED  {name}: {lic}")
    for name, lic in unknown:
        print(f"UNKNOWN  {name}: {lic}  (classify it, or add to EXCEPTIONS)")
    if blocked or unknown:
        print(f"\n{len(blocked)} incompatible, {len(unknown)} unclassified.")
        return 1
    print("All dependency licences are compatible with Apache-2.0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
