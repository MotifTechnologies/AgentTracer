"""Agent-tracer: record agent runs as training-ready trajectories."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("motif-agent-tracer")
except PackageNotFoundError:
    # Imported from a source tree without an install; pyproject.toml is the
    # source of truth there.
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
