import pytest

from agent_tracer.run.runner import describe_exception


class TestExceptionGroupIsUnwrapped:
    """stirrup runs tools in a TaskGroup, so a tool-side failure reaches the
    runner wrapped. str() on the wrapper names no cause, which left 21 of one
    run's 60 failures recorded as 'unhandled errors in a TaskGroup'."""

    def test_the_cause_is_named(self):
        group = ExceptionGroup("boom", [TimeoutError("read timed out after 300s")])
        assert describe_exception(group) == "ExceptionGroup[TimeoutError: read timed out after 300s]"

    def test_several_causes_are_kept(self):
        group = ExceptionGroup("boom", [ValueError("a"), KeyError("b")])
        described = describe_exception(group)
        assert "ValueError: a" in described and "KeyError" in described

    def test_nesting_is_followed(self):
        inner = ExceptionGroup("inner", [RuntimeError("daemon gone")])
        assert "RuntimeError: daemon gone" in describe_exception(ExceptionGroup("outer", [inner]))

    def test_deep_nesting_terminates(self):
        exc: BaseException = RuntimeError("leaf")
        for _ in range(12):
            exc = ExceptionGroup("wrap", [exc])
        assert describe_exception(exc)  # no recursion error

    def test_a_plain_exception_is_unchanged(self):
        assert describe_exception(ValueError("bad input")) == "ValueError: bad input"

    def test_an_empty_message_still_names_the_type(self):
        assert describe_exception(RuntimeError()) == "RuntimeError"
