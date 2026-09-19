"""Snowflake connection and error masking: key-pair auth, every parameter from the environment.

Adapted from C0k11/quantai infra/snowflake/sfconn.py (MIT). Docstring and comments translated
from Chinese; object-name defaults changed from the upstream QUANTAI_* objects to this project's,
and mask() reworked (the S3 bucket and IAM ARN patterns were dropped because this project loads
from a local internal stage rather than a data lake, and the private key path is masked instead).

Locally the values come from a git-ignored .env.snowflake.local passed with --env-file; the
repository holds no account identifier and no private key.

The object-name defaults below mirror the objects Phase 3 creates in infra/snowflake/setup.sql.
Change one, change both.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_USER = "LP_LENS_REPORTER_USER"
DEFAULT_ROLE = "LP_LENS_REPORTER"
DEFAULT_WAREHOUSE = "LP_LENS_WH"
DEFAULT_DATABASE = "LP_LENS_DEV"


def read_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into the environment. Variables already set are not overwritten."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key, value = s.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def connect(query_tag: str):
    """Open a key-pair authenticated connection. Account and private key path are required."""
    import snowflake.connector

    e = os.environ
    return snowflake.connector.connect(
        account=e["SNOWFLAKE_ACCOUNT"],
        user=e.get("SNOWFLAKE_USER", DEFAULT_USER),
        role=e.get("SNOWFLAKE_ROLE", DEFAULT_ROLE),
        warehouse=e.get("SNOWFLAKE_WAREHOUSE", DEFAULT_WAREHOUSE),
        database=e.get("SNOWFLAKE_DATABASE", DEFAULT_DATABASE),
        authenticator="SNOWFLAKE_JWT",
        private_key_file=e["SNOWFLAKE_PRIVATE_KEY_PATH"],
        login_timeout=30,
        session_parameters={"QUERY_TAG": query_tag},
    )


def mask(text: str, *extra: str) -> str:
    """Replace the account identifier, the private key path and any extra values before printing.

    Snowflake driver errors can echo back the account identifier and the key path, so every script
    passes error text through here before it reaches stdout or a CI log.
    """
    secrets = [
        os.environ.get("SNOWFLAKE_ACCOUNT", ""),
        os.environ.get("SNOWFLAKE_ACCOUNT_LOCATOR", ""),
        os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", ""),
        *extra,
    ]
    out = str(text)
    # Longest first, so a value that contains another is masked whole rather than partly.
    for s in sorted({s for s in secrets if s}, key=len, reverse=True):
        out = out.replace(s, "<masked>").replace(s.upper(), "<masked>").replace(s.lower(), "<masked>")
    return re.sub(r"[-\w./]+\.p8\b", "<masked>", out)
