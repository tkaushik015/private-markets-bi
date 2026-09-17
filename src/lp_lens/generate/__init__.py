"""Seeded synthetic private markets data generator.

Private markets fund-level data is not publicly available, so LP Lens generates its own. The
generator is seeded and deterministic: one seed in the config drives every draw, and the same seed
with the same config reproduces byte-identical Parquet. That removes the live-network dependency
that made the audited predecessor project's ETL non-reproducible, and it means a metric can be
reconciled against an expected value that does not move between runs.

All output is fabricated. No manager, fund or investor in it is a real entity.
"""

from __future__ import annotations

from .config import GeneratorConfig, load_config
from .dataset import generate_dataset
from .flows import DISTRIBUTION_TYPES, FLOW_DIRECTION, FLOW_TYPES, PAID_IN_TYPES
from .writer import TABLE_ORDER, TABLE_SCHEMAS, file_hashes, write_dataset

__all__ = [
    "DISTRIBUTION_TYPES",
    "FLOW_DIRECTION",
    "FLOW_TYPES",
    "PAID_IN_TYPES",
    "TABLE_ORDER",
    "TABLE_SCHEMAS",
    "GeneratorConfig",
    "file_hashes",
    "generate_dataset",
    "load_config",
    "write_dataset",
]
