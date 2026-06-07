from __future__ import annotations

import pytest

from data_quality_toolkit.application.workflow.executor import execute


def test_execute_calls_function_with_args_kwargs():
    def f(a, b, scale=1):
        return (a + b) * scale

    out = execute(f, 2, 3, scale=2)
    assert out == 10


def test_execute_propagates_exception():
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        execute(boom)
