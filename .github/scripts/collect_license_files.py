"""Collect pypdfium2's complete installed license directory with raw-byte fidelity."""

import base64
import importlib.metadata
import json


def collect() -> dict:
    try:
        distribution = importlib.metadata.distribution("pypdfium2")
    except importlib.metadata.PackageNotFoundError:
        return {}
    # Inspect the directory, not only RECORD: extra files must invalidate review.
    roots = {
        distribution.locate_file(path).parents[len(path.parts) - 2]
        for path in distribution.files or []
        if ".dist-info" in path.parts[0] and "licenses" in path.parts[1:]
    }
    if len(roots) != 1:
        raise ValueError("Expected one installed pypdfium2 license directory")
    root = roots.pop() / "licenses"
    attachments = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            attachments.append(
                {
                    "license": {
                        "name": "declared license file: "
                        + path.relative_to(root).as_posix(),
                        "text": {
                            "contentType": "text/plain",
                            "encoding": "base64",
                            "content": base64.b64encode(path.read_bytes()).decode(
                                "ascii"
                            ),
                        },
                    }
                }
            )
    return {
        "name": "pypdfium2",
        "version": distribution.version,
        "licenses": attachments,
    }


if __name__ == "__main__":
    print(json.dumps(collect()))
