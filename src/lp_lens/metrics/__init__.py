"""Return metrics for private markets cash flow streams.

This is the single implementation of IRR and PME in the project. The dbt Python models import it
rather than reimplementing the arithmetic in SQL, so a dbt mart and a Python reconciliation test
cannot drift apart: there is only one definition to drift from.
"""

from __future__ import annotations

from .returns import build_lp_flow_vector, ks_pme, xirr

__all__ = ["build_lp_flow_vector", "ks_pme", "xirr"]
