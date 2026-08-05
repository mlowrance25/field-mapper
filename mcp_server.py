"""FieldMapper MCP server.

Second entry point onto this repo's deterministic analyzers (see
utils/completeness.py, utils/coverage.py), alongside the existing
Streamlit UI (app.py). Runs via stdio by default for local development —
see PLAN-009 Phase 6 for the HTTP/SSE + auth mode used by network-reachable
clients (e.g. CAM).
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from mcp.server import MCPServer

from utils.completeness import analyze_completeness_batch
from utils.coverage import evaluate_coverage
from utils.ingest import parse_json

logger = logging.getLogger(__name__)
mcp = MCPServer("fieldmapper")

# ---------------------------------------------------------------------------
# Dataset store — in-memory only, no persistence. Matches this project's
# existing "nothing written to disk" stance (CLAUDE.md, PRD-002 NFRs).
# ---------------------------------------------------------------------------

_datasets: dict[str, pd.DataFrame] = {}
_dataset_meta: dict[str, dict] = {}

_DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / "data"
_DATA_ROOT = Path(os.environ.get("FIELDMAPPER_DATA_ROOT", str(_DEFAULT_DATA_ROOT))).resolve()
_MAX_FILE_SIZE_MB = 50
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _resolve_dataset_path(path: str) -> Path:
    """Resolve `path` against the FIELDMAPPER_DATA_ROOT allowlist.

    Rejects URL-shaped strings (pandas' readers accept URLs directly,
    which would otherwise make this an arbitrary-fetch primitive) and any
    path that escapes the allowed root, whether via `..` traversal or an
    absolute path pointing elsewhere.
    """
    if _URL_SCHEME_RE.match(path):
        raise ValueError(f"URL-shaped paths are not allowed: {path!r}")

    logger.info("About to resolve path")
    candidate = Path(path)
    candidate = candidate.resolve() if candidate.is_absolute() else (_DATA_ROOT / candidate).resolve()
    logger.info(f"Resolving {path!r} to {candidate!r}")

    try:
        candidate.relative_to(_DATA_ROOT)
    except ValueError:
        raise ValueError(f"Path escapes the allowed data root ({_DATA_ROOT}): {path!r}") from None

    if not candidate.is_file():
        raise ValueError(f"File not found under data root: {path!r}")

    return candidate


def _check_size(path: Path) -> None:
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > _MAX_FILE_SIZE_MB:
        raise ValueError(f"File is {size_mb:.1f}MB — exceeds the {_MAX_FILE_SIZE_MB}MB limit.")


def _get_df(dataset_id: str) -> pd.DataFrame:
    if dataset_id not in _datasets:
        raise ValueError(f"Unknown dataset_id: {dataset_id!r} — call load_dataset first.")
    return _datasets[dataset_id]


@mcp.tool()
def health_check() -> dict:
    """Confirm the FieldMapper MCP server is running and reachable."""
    return {"status": "ok"}


@mcp.tool()
def load_dataset(path: str) -> dict:
    """Load a CSV or JSON dataset from disk and return a dataset_id for use
    in later tool calls (list_fields, analyze_completeness_tool, etc.).

    `path` is resolved against the FIELDMAPPER_DATA_ROOT allowlisted
    directory (env var; defaults to a `data/` directory next to this
    script, regardless of the launching client's working directory).
    Paths that escape this root — via `..` traversal or an absolute path
    elsewhere — are rejected, as are URL-shaped strings (http://, s3://,
    ...). Files over 50MB are rejected.

    JSON is flattened one level deep (lists of records, or a dict wrapping
    a list of records). Columns that are still nested after that are
    reported back in `nested_columns` rather than silently dropped — the
    values are preserved as-is in those columns.
    """
    logger.info(f"Loading dataset from {path!r}")
    resolved = _resolve_dataset_path(path)
    _check_size(resolved)

    nested_columns: list[str] = []
    suffix = resolved.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(resolved)
    elif suffix == ".json":
        with open(resolved) as f:
            raw = json.load(f)
        df, nested_columns = parse_json(raw)
    else:
        raise ValueError(f"Unsupported file type: {suffix!r} (expected .csv or .json)")

    if df.empty:
        raise ValueError("File contains no rows.")

    dataset_id = str(uuid.uuid4())
    _datasets[dataset_id] = df
    _dataset_meta[dataset_id] = {
        "path": str(resolved),
        "rows": len(df),
        "columns": list(df.columns),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }

    result = {"dataset_id": dataset_id, "rows": len(df), "columns": list(df.columns)}
    if nested_columns:
        result["nested_columns"] = nested_columns
    return result


@mcp.tool()
def list_fields(dataset_id: str) -> dict:
    """Return column names and dtypes for a loaded dataset."""
    df = _get_df(dataset_id)
    return {col: str(dtype) for col, dtype in df.dtypes.items()}


@mcp.tool()
def list_datasets() -> list[dict]:
    """List all currently-loaded datasets and their metadata."""
    return [{"dataset_id": ds_id, **meta} for ds_id, meta in _dataset_meta.items()]


@mcp.tool()
def unload_dataset(dataset_id: str) -> dict:
    """Free a loaded dataset from memory. There's no automatic eviction in
    this version — datasets stay loaded until explicitly unloaded or the
    server restarts.
    """
    _get_df(dataset_id)  # raises a clear error if unknown, before mutating anything
    del _datasets[dataset_id]
    del _dataset_meta[dataset_id]
    return {"dataset_id": dataset_id, "unloaded": True}


@mcp.tool()
def analyze_completeness_tool(dataset_id: str, units: list[dict]) -> list[dict]:
    """Compare completeness across one or more declared units of a loaded
    dataset in a single pass.

    `units` is a list of `{"name": str, "columns": [str, ...]}`. Each unit
    must declare 1+ columns. Any unit with 2+ columns automatically gets
    its constituent columns added as their own single-column entries too
    (deduped by column name — no duplicate rows if a column is already
    declared standalone or appears in more than one multi-column unit).
    Results are ordered single-column units first (in order of first
    appearance), then multi-column units in declaration order.

    Null, empty-string, and whitespace-only values are all treated as
    "not present," consistently across single- and multi-column units.

    Example `units`:
        [{"name": "lat", "columns": ["lat"]},
         {"name": "lat+lon", "columns": ["lat", "lon"]}]
    (the second entry alone would already auto-generate a "lat" and "lon"
    single-column entry, so declaring "lat" separately above is optional —
    shown here only to illustrate the dedupe behavior.)

    Returns one result dict per unit (declared + auto-generated), each with:
        name, columns, total_rows,
        complete_count, complete_rate, empty_count, empty_rate,
        partial_count, partial_rate,       # always 0 for single-column units
        partial_rows, missing_patterns     # always empty for single-column units
    """
    df = _get_df(dataset_id)
    return analyze_completeness_batch(df, units)


@mcp.tool()
def evaluate_coverage_tool(
    dataset_id: str, units: dict[str, list[str]], expressions: list[str]
) -> list[dict]:
    """Evaluate boolean coverage expressions over a loaded dataset — answers
    "what fraction of rows can satisfy an outcome via any of several
    fallback paths," not "how complete is a single field."

    `units` is a mapping of unit name -> columns, e.g.:
        {"lat": ["lat"], "lon": ["lon"], "lat_lon": ["lat", "lon"],
         "linestring": ["linestring"]}
    A unit is "present" on a row when ALL of its columns are non-null,
    non-empty, non-whitespace (same presence rule as
    analyze_completeness_tool).

    `expressions` is a list of strings built from those unit names plus
    AND, OR, and one level of parentheses. THE GRAMMAR IS DELIBERATELY
    MINIMAL — there is no UI here stopping an invalid expression the way
    the app's click-to-build composer does, so read this carefully:
      - Allowed:    "lat_lon AND linestring"
                    "lat_lon OR linestring"
                    "(lat AND lon) OR linestring"
      - NOT allowed: NOT (no negation of any kind)
                     nested parentheses, e.g. "((lat AND lon))"
                     any unit name not present in `units`
    A malformed expression raises a clear error identifying the problem
    and the offending expression string; it does not silently misparse.

    Expressions are CUMULATIVE, not a partition: the same row can satisfy
    more than one expression (e.g. a row with both lat_lon and linestring
    present satisfies both "lat_lon" and "linestring" individually), so
    rows_satisfied values across expressions are not expected to sum to
    the dataset's total row count.

    Returns one result dict per expression, in the order given:
        {"expression": str, "rows_satisfied": int, "rate": float}

    Worked example: to check whether every row can produce a valid
    geometry via a direct linestring OR a computable lat/lon pair OR a
    geocodable address, declare those three units and evaluate:
        "linestring OR lat_lon OR address"
    A `rate` of 1.0 means the dataset can hit 100% coverage of that
    outcome through at least one of the three paths.
    """
    df = _get_df(dataset_id)
    return evaluate_coverage(df, units, expressions)


if __name__ == "__main__":
    logger.info("Starting FieldMapper MCP server...")
    try:
        mcp.run()
    except Exception:
        logger.exception("FieldMapper MCP server failed.")
