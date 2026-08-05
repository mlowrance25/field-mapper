import pandas as pd


def analyze_cardinality(df: pd.DataFrame, field_a: str, field_b: str) -> dict:
    """Compute the mapping shape between two fields deterministically.

    Nulls on either side are excluded from fan-out counts and reported
    separately as coverage figures. Returns both A→B and B→A mapping tables
    so the caller can display whichever direction is declared.
    """
    if field_a == field_b:
        raise ValueError("field_a and field_b must be different fields")

    total_rows = len(df)
    null_a = int(df[field_a].isna().sum())
    null_b = int(df[field_b].isna().sum())

    working = df[[field_a, field_b]].dropna()
    working_rows = len(working)

    if working_rows == 0:
        return {
            "field_a": field_a,
            "field_b": field_b,
            "total_rows": total_rows,
            "working_rows": 0,
            "null_a": null_a,
            "null_b": null_b,
            "distinct_a": 0,
            "distinct_b": 0,
            "dominant_shape": None,
            "conformance_ab": None,
            "conformance_ba": None,
            "violation_count_ab": 0,
            "violation_count_ba": 0,
            "violations_ab": [],
            "violations_ba": [],
            "mapping_table_ab": [],
            "mapping_table_ba": [],
        }

    fanout_ab = working.groupby(field_a)[field_b].nunique()
    fanout_ba = working.groupby(field_b)[field_a].nunique()

    distinct_a = len(fanout_ab)
    distinct_b = len(fanout_ba)

    max_ab = int(fanout_ab.max())
    max_ba = int(fanout_ba.max())

    if max_ab <= 1 and max_ba <= 1:
        shape = "1-to-1"
    elif max_ab > 1 and max_ba <= 1:
        shape = "1-to-many"
    elif max_ab <= 1 and max_ba > 1:
        shape = "many-to-1"
    else:
        shape = "many-to-many"

    violations_ab = fanout_ab[fanout_ab > 1].index.tolist()
    violations_ba = fanout_ba[fanout_ba > 1].index.tolist()

    conformance_ab = (distinct_a - len(violations_ab)) / distinct_a if distinct_a else 1.0
    conformance_ba = (distinct_b - len(violations_ba)) / distinct_b if distinct_b else 1.0

    def _build_table(df_work, key_col, val_col):
        s = df_work.groupby(key_col)[val_col].apply(
            lambda x: sorted(x.astype(str).unique().tolist())
        )
        tbl = s.reset_index()
        tbl.columns = ["key_value", "mapped_values"]
        tbl["fan_out"] = tbl["mapped_values"].apply(len)
        tbl["key_value"] = tbl["key_value"].astype(str)
        return tbl.sort_values("fan_out", ascending=False).to_dict("records")

    return {
        "field_a": field_a,
        "field_b": field_b,
        "total_rows": total_rows,
        "working_rows": working_rows,
        "null_a": null_a,
        "null_b": null_b,
        "distinct_a": distinct_a,
        "distinct_b": distinct_b,
        "dominant_shape": shape,
        "conformance_ab": conformance_ab,
        "conformance_ba": conformance_ba,
        "violation_count_ab": len(violations_ab),
        "violation_count_ba": len(violations_ba),
        "violations_ab": [str(v) for v in violations_ab],
        "violations_ba": [str(v) for v in violations_ba],
        "mapping_table_ab": _build_table(working, field_a, field_b),
        "mapping_table_ba": _build_table(working, field_b, field_a),
    }
