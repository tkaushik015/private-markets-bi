"""CLI: python -m lp_lens.generate --config configs/generator.yaml --out data/raw"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .dataset import generate_dataset
from .writer import TABLE_ORDER, file_hashes, write_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lp_lens.generate",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, required=True, help="generator config YAML")
    parser.add_argument("--out", type=Path, required=True, help="output directory for Parquet files")
    parser.add_argument(
        "--print-hashes",
        action="store_true",
        help="print the SHA-256 of each written file, for the determinism check",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    tables = generate_dataset(config)
    write_dataset(tables, args.out)

    print(f"[generate] seed {config.seed}, as-of {config.as_of_date}, output {args.out}")
    width = max(len(name) for name in TABLE_ORDER)
    for name in TABLE_ORDER:
        print(f"  {name:<{width}}  {len(tables[name]):>7,} rows")
    print(f"  {'total':<{width}}  {sum(len(tables[name]) for name in TABLE_ORDER):>7,} rows")

    if args.print_hashes:
        print("[generate] sha256")
        for name, digest in file_hashes(args.out).items():
            print(f"  {name:<{width}}  {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
