"""agent_tracer.__version__ reflects the installed package metadata."""

import importlib.metadata

import agent_tracer


def test_version_matches_installed_metadata():
    assert agent_tracer.__version__ == importlib.metadata.version("motif-agent-tracer")
