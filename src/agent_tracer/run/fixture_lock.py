"""Exclusive output reservation for native fixture collectors.

An interrupted collector leaves its reservation for explicit operator inspection.
Never steal a lock based on a PID which may belong to a different host.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_tracer.config.schema import ConfigError


@contextmanager
def exclusive_fixture_output(output: Path) -> Iterator[None]:
    output.mkdir(parents=True, exist_ok=True)
    path = output / ".fixture-collector.lock"
    reservation = json.dumps(
        {"pid": os.getpid(), "host": socket.gethostname(), "token": uuid.uuid4().hex}
    ).encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ConfigError(
            "fixture collector reservation exists; inspect owned process and journals before explicit recovery"
        ) from exc
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(reservation)
            out.flush()
            os.fsync(out.fileno())
        yield
    finally:
        # A replaced file belongs to someone else; leave it untouched.
        if path.is_file() and not path.is_symlink():
            current = path.stat()
            if (current.st_dev, current.st_ino) == (
                identity.st_dev,
                identity.st_ino,
            ) and path.read_bytes() == reservation:
                path.unlink()
