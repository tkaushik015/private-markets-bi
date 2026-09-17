"""Smoke test for the Phase 0 scaffold.

Guards the src layout: if lp_lens stops being importable, every later test fails confusingly, and
the cause (a bad editable install, a renamed package directory) is not obvious from those failures.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_package_imports() -> None:
    import lp_lens

    assert lp_lens.__version__


def test_dbt_layout_exists() -> None:
    """The three model layers are committed before any model exists, so assert they survive."""
    models = REPO_ROOT / "warehouse" / "models"
    for layer in ("staging", "intermediate", "marts"):
        assert (models / layer).is_dir(), f"missing dbt layer: {layer}"


def test_reconcile_script_is_importable() -> None:
    """The reconcile script's comparison helpers must load without a Snowflake connection."""
    import importlib.util

    path = REPO_ROOT / "infra" / "snowflake" / "reconcile.py"
    spec = importlib.util.spec_from_file_location("reconcile", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Integers compare exactly; floats get rel_tol=1e-9. Both directions are asserted because a
    # tolerance applied to integers would silently accept an off-by-one in a row count.
    assert module.cells_equal(3, 3)[0]
    assert not module.cells_equal(3, 4)[0]
    assert module.cells_equal(1.0, 1.0 + 1e-12)[0]
    assert not module.cells_equal(1.0, 1.0 + 1e-6)[0]
