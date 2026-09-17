"""Guards the src layout: if pm_bi stops being importable, every later test fails confusingly."""

from __future__ import annotations


def test_package_imports() -> None:
    import pm_bi

    assert pm_bi.__version__
