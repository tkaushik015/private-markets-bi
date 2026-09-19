"""Offline tests for the Phase 3 Snowflake path. None of these open a Snowflake connection."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

from lp_lens.generate import generate_dataset, load_config, write_dataset
from lp_lens.generate.writer import TABLE_ORDER

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def raw_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("raw")
    write_dataset(generate_dataset(load_config(REPO / "configs" / "generator.yaml")), out)
    return out


def test_check_snapshot_accepts_a_complete_generator_run(raw_dir: Path) -> None:
    load_raw = _load("load_raw", "infra/snowflake/load_raw.py")
    counts = load_raw.check_snapshot(raw_dir)
    assert set(counts) == set(TABLE_ORDER)
    assert all(n > 0 for n in counts.values())


def test_check_snapshot_refuses_a_missing_table(raw_dir: Path, tmp_path: Path) -> None:
    load_raw = _load("load_raw", "infra/snowflake/load_raw.py")
    dest = tmp_path / "partial"
    dest.mkdir()
    for name in TABLE_ORDER[:-1]:
        (dest / f"{name}.parquet").write_bytes((raw_dir / f"{name}.parquet").read_bytes())
    with pytest.raises(load_raw.SnapshotError, match="missing"):
        load_raw.check_snapshot(dest)


def test_check_snapshot_refuses_an_empty_table(raw_dir: Path, tmp_path: Path) -> None:
    load_raw = _load("load_raw", "infra/snowflake/load_raw.py")
    import pyarrow as pa
    import pyarrow.parquet as pq

    dest = tmp_path / "empty"
    dest.mkdir()
    for name in TABLE_ORDER:
        (dest / f"{name}.parquet").write_bytes((raw_dir / f"{name}.parquet").read_bytes())
    schema = pq.read_schema(dest / "managers.parquet")
    pq.write_table(pa.table({field.name: [] for field in schema}, schema=schema), dest / "managers.parquet")
    with pytest.raises(load_raw.SnapshotError, match="empty"):
        load_raw.check_snapshot(dest)


def test_check_snapshot_refuses_an_orphaned_commitment(raw_dir: Path, tmp_path: Path) -> None:
    load_raw = _load("load_raw", "infra/snowflake/load_raw.py")
    import pandas as pd

    dest = tmp_path / "orphan"
    dest.mkdir()
    for name in TABLE_ORDER:
        (dest / f"{name}.parquet").write_bytes((raw_dir / f"{name}.parquet").read_bytes())
    commitments = pd.read_parquet(dest / "commitments.parquet")
    commitments.loc[commitments.index[0], "fund_id"] = "FUND_MISSING"
    commitments.to_parquet(dest / "commitments.parquet", index=False)
    with pytest.raises(load_raw.SnapshotError, match="commitments"):
        load_raw.check_snapshot(dest)


def test_metrics_wheel_is_the_same_returns_module(tmp_path: Path) -> None:
    """The slim wheel is a packaging of returns.py, not a second solver."""
    builder = _load("build_metrics_wheel", "infra/snowflake/build_metrics_wheel.py")
    wheel = builder.build_metrics_wheel(tmp_path)
    assert wheel.name == "lp_lens-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "lp_lens/metrics/returns.py" in names
        assert not any("generate" in name for name in names)
        wheeled = archive.read("lp_lens/metrics/returns.py")
    source = (REPO / "src" / "lp_lens" / "metrics" / "returns.py").read_bytes()
    assert wheeled == source, "the staged wheel must be byte-identical to src/lp_lens/metrics/returns.py"


def test_reconcile_negative_control_catches_one_changed_cell() -> None:
    reconcile = _load("reconcile", "infra/snowflake/reconcile.py")
    cols = ["fund_id", "tvpi"]
    rows = [("FUND0001", 1.25), ("FUND0002", 0.90)]
    perturbed, column, row_idx = reconcile.perturb_one_numeric_cell(cols, rows)
    assert column == "tvpi"
    assert row_idx == 0
    assert perturbed[0][1] == pytest.approx(1.375)
    assert perturbed[1] == rows[1]

    result = reconcile.compare_table("fct_demo", cols, rows, cols, perturbed)
    assert result["problems"]
    assert result["columns_mismatched"] == ["tvpi"]

    identical = reconcile.compare_table("fct_demo", cols, rows, cols, rows)
    assert not identical["problems"]


def test_reconcile_negative_control_helper_returns_zero_on_detection() -> None:
    reconcile = _load("reconcile", "infra/snowflake/reconcile.py")
    duck = {"dim_demo": (["n"], [(1,), (2,)])}
    assert reconcile.run_negative_control(duck) == 0


def test_setup_sql_uses_placeholders_not_account_identifiers() -> None:
    text = (REPO / "infra" / "snowflake" / "setup.sql").read_text(encoding="utf-8")
    assert "<transformer-rsa-public-key>" in text
    assert "<loader-rsa-public-key>" in text
    assert "<reporter-rsa-public-key>" in text
    assert "LP_LENS_DEV" in text and "LP_LENS_PROD" in text
    assert "LP_LENS_LOADER" in text and "LP_LENS_TRANSFORMER" in text and "LP_LENS_REPORTER" in text
    assert "AUTO_SUSPEND = 60" in text
    assert "CREDIT_QUOTA = 20" in text
    # No Snowflake account locator (xy12345.us-east-1 style) and no PEM body.
    assert "BEGIN RSA PRIVATE" not in text
    assert "us-east-" not in text
    assert "xy" + "12345" not in text


def test_profiles_declare_duckdb_default_and_three_snowflake_targets() -> None:
    text = (REPO / "warehouse" / "profiles.yml").read_text(encoding="utf-8")
    assert "target: local" in text
    for name in ("snowflake_dev", "snowflake_ci", "snowflake_prod"):
        assert f"{name}:" in text
    assert "env_var('SNOWFLAKE_ACCOUNT')" in text
    assert "private_key_path" in text
    assert "password:" not in text


def test_python_models_configure_snowpark_imports_lazily() -> None:
    """The wheel cannot be imported at module top: dbt.config(imports=) has not run yet."""
    for relative in (
        "warehouse/models/intermediate/int_returns_by_quarter.py",
        "warehouse/models/intermediate/int_portfolio_returns_by_quarter.py",
    ):
        source = (REPO / relative).read_text(encoding="utf-8")
        assert "from lp_lens.metrics.returns import" in source
        top, _, rest = source.partition("def compute_")
        assert "from lp_lens.metrics.returns import" not in top
        assert "from lp_lens.metrics.returns import" in rest
        assert "LP_LENS_SNOWPARK_WHEEL" in source
        assert 'dbt.config(materialized="table")' in source
