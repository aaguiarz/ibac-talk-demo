"""Shared utilities for the MCP authorization demo.

Contains helpers duplicated across agent.py, mcp_server.py,
task_authz_middleware.py, and test files.  Only depends on stdlib
+ openfga_sdk (no circular imports).
"""

from __future__ import annotations

import os
import re
from typing import Any

from openfga_sdk.client.models.write_conflict_opts import (
    ClientWriteRequestOnDuplicateWrites,
    ClientWriteRequestOnMissingDeletes,
    ConflictOptions,
)

# ---------------------------------------------------------------------------
# OpenFGA write options (ignore duplicate writes / missing deletes)
# ---------------------------------------------------------------------------

FGA_WRITE_OPTS = {
    "conflict": ConflictOptions(
        on_duplicate_writes=ClientWriteRequestOnDuplicateWrites.IGNORE,
        on_missing_deletes=ClientWriteRequestOnMissingDeletes.IGNORE,
    )
}

# ---------------------------------------------------------------------------
# FGA ID sanitization
# ---------------------------------------------------------------------------

_FGA_ID_UNSAFE = re.compile(r"[^a-zA-Z0-9_\-.]")


def sanitize_fga_id(value: str) -> str:
    """Sanitize a value for use in an OpenFGA object ID.

    Replaces characters not allowed in OpenFGA IDs (like : / spaces)
    with underscores.
    """
    return _FGA_ID_UNSAFE.sub("_", value)


# ---------------------------------------------------------------------------
# .env file loader
# ---------------------------------------------------------------------------


def load_env(path: str) -> None:
    """Load key=value pairs from *path* into ``os.environ`` (setdefault).

    Existing environment variables take precedence, so command-line
    overrides like ``FGA_STORE_ID=x make run-auto`` still work.
    The Makefile ``run*`` targets source ``.env`` explicitly to ensure
    values updated by ``make fga-reset`` take effect.

    Skips blank lines and ``#``-comments.  Does nothing if the file
    does not exist.
    """
    if not os.path.exists(path):
        return

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


# ---------------------------------------------------------------------------
# MCP result text extraction
# ---------------------------------------------------------------------------


def extract_text(result: Any) -> str:
    """Extract text from a ``CallToolResult`` (or plain string).

    Handles both FastMCP ``CallToolResult`` objects (with ``.content``
    list) and plain strings.
    """
    if isinstance(result, str):
        return result
    parts = []
    for content in result.content:
        if hasattr(content, "text"):
            parts.append(content.text)
        else:
            parts.append(str(content))
    return "".join(parts)
