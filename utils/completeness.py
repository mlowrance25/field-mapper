import pandas as pd
import logging

logger = logging.getLogger(__name__)

def _serializable_index(idx):
    try:
        return int(idx)
    except (TypeError, ValueError):
        return str(idx)


def _presence_mask(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Per-column, per-row presence: non-null AND not blank/whitespace-only.

    Applied identically regardless of unit size so single- and multi-column
    checks treat null, empty-string, and whitespace-only values the same way.
    """
    mask = pd.DataFrame(index=df.index)
    for c in columns:
        col = df[c]
        notna = col.notna()
        if pd.api.types.is_numeric_dtype(col) or pd.api.types.is_bool_dtype(col):
            mask[c] = notna
        else:
            non_blank = col.astype(str).str.strip() != ""
            mask[c] = notna & non_blank
    return mask


def analyze_completeness(df: pd.DataFrame, columns: list[str]) -> dict:
    """Classify every row of a declared unit as complete, empty, or partial.

    Built on a single primitive — the per-row presence signature across the
    declared columns (`_presence_mask`). complete/empty are the all-True
    and all-False slices of that signature; partial is everything else, and
    the missing-pattern breakdown is just that partial slice grouped by its
    exact set of null columns. A single-column unit can never be partial —
    complete/empty are complementary by construction, no special-casing
    needed. Standalone so it can be called without going through the page.
    """
    if len(columns) < 1:
        raise ValueError("completeness requires at least 1 column")
    missing_cols = [c for c in columns if c not in df.columns]
    if missing_cols:
        raise ValueError(f"columns not in dataset: {missing_cols}")

    total_rows = len(df)
    presence = _presence_mask(df, columns)

    complete_mask = presence.all(axis=1)
    empty_mask = ~presence.any(axis=1)
    partial_mask = ~complete_mask & ~empty_mask

    complete_count = int(complete_mask.sum())
    empty_count = int(empty_mask.sum())
    partial_count = int(partial_mask.sum())

    def _rate(n):
        return n / total_rows if total_rows else 0.0

    partial_missing = ~presence[partial_mask]
    partial_rows = []
    missing_patterns: dict[str, int] = {}
    for idx, row in partial_missing.iterrows():
        row_missing = [c for c in columns if row[c]]
        partial_rows.append({"index": _serializable_index(idx), "missing": row_missing})
        key = ", ".join(row_missing)
        missing_patterns[key] = missing_patterns.get(key, 0) + 1

    return {
        "columns": columns,
        "total_rows": total_rows,
        "complete_count": complete_count,
        "complete_rate": _rate(complete_count),
        "empty_count": empty_count,
        "empty_rate": _rate(empty_count),
        "partial_count": partial_count,
        "partial_rate": _rate(partial_count),
        "partial_rows": partial_rows,
        "missing_patterns": missing_patterns,
    }


def analyze_completeness_batch(df: pd.DataFrame, units: list[dict]) -> list[dict]:
    """Run analyze_completeness over multiple declared units in one pass.

    `units` is a list of `{"name": str, "columns": [str, ...]}`. Any unit
    with 2+ columns has its constituent columns auto-generated as their own
    single-column entries — deduped by column name, regardless of whether
    that column was declared standalone, appears in more than one
    multi-column unit, or both. Results are ordered single-column units
    first (in order of first appearance across the declared list), then
    multi-column units in declaration order — matching the comparison
    table's required row order.
    """
    logger.info("Analyzing completeness Batch")
    if not units:
        raise ValueError("at least one unit must be declared")

    single_cols_order: list[str] = []
    seen_single: set[str] = set()
    multi_entries: list[dict] = []

    for u in units:
        cols = u["columns"]
        if not cols:
            raise ValueError("unit must declare at least one column")
        name = u.get("name") or " + ".join(cols)
        if len(cols) == 1:
            c = cols[0]
            if c not in seen_single:
                seen_single.add(c)
                single_cols_order.append(c)
        else:
            multi_entries.append({"name": name, "columns": cols})
            for c in cols:
                if c not in seen_single:
                    seen_single.add(c)
                    single_cols_order.append(c)

    results = []
    for c in single_cols_order:
        r = analyze_completeness(df, [c])
        r["name"] = c
        results.append(r)
    for u in multi_entries:
        r = analyze_completeness(df, u["columns"])
        r["name"] = u["name"]
        results.append(r)
    return results