"""Independent random streams derived from the single configured seed.

Every draw in the generator comes from one of these streams and nothing uses the global numpy
random state. Streams are spawned from one `SeedSequence` rather than being seeded by hand, which
buys two properties worth having:

1. The streams are statistically independent, so drawing more numbers in one table cannot shift
   the values another table receives.
2. Adding a new stream at the end of `STREAM_NAMES` leaves the existing streams' output unchanged,
   so the generator can grow without invalidating a previously generated dataset.

Order matters: inserting a name in the middle of `STREAM_NAMES` renumbers the children and changes
every table after it. Append, never insert.
"""

from __future__ import annotations

import numpy as np

STREAM_NAMES: tuple[str, ...] = (
    "managers",
    "funds",
    "investors",
    "commitments",
    "cash_flows",
    "nav",
    "fx",
    "index",
)


def make_streams(seed: int) -> dict[str, np.random.Generator]:
    """Return one independent `Generator` per name in `STREAM_NAMES`."""
    root = np.random.SeedSequence(seed)
    children = root.spawn(len(STREAM_NAMES))
    return {name: np.random.default_rng(child) for name, child in zip(STREAM_NAMES, children, strict=True)}
