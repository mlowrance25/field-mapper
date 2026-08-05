import pandas as pd


LOW_CARDINALITY_THRESHOLD = 20


def profile_dataframe(df: pd.DataFrame) -> list[dict]:
    """Compute per-field statistics from a DataFrame."""
    profiles = []
    total_rows = len(df)

    for col in df.columns:
        series = df[col]
        null_count = series.isna().sum()
        non_null = series.dropna()

        null_rate = round(null_count / total_rows, 4) if total_rows > 0 else 0.0
        presence_pct = round(1 - null_rate, 4)
        cardinality = int(series.nunique(dropna=True))
        cardinality_ratio = round(cardinality / total_rows, 4) if total_rows > 0 else 0.0

        distinct_values = (
            sorted([str(v) for v in non_null.unique()])
            if cardinality <= LOW_CARDINALITY_THRESHOLD
            else None
        )

        inferred_type = _infer_type(series)

        min_value = max_value = mean_value = None
        if inferred_type in ("integer", "float") and len(non_null) > 0:
            min_value = round(float(non_null.min()), 4)
            max_value = round(float(non_null.max()), 4)
            mean_value = round(float(non_null.mean()), 4)

        sample_values = [str(v) for v in non_null.head(5).tolist()]

        profiles.append({
            "field_name":      col,
            "inferred_type":   inferred_type,
            "total_rows":      total_rows,
            "num_present":     int(total_rows - null_count),
            "missing_pct":     round(null_rate * 100, 1),
            "null_rate":       null_rate,
            "presence_pct":    presence_pct,
            "cardinality":     cardinality,
            "cardinality_ratio": cardinality_ratio,
            "distinct_values": distinct_values,
            "min_value":       min_value,
            "max_value":       max_value,
            "mean_value":      mean_value,
            "sample_values":   sample_values,
        })

    return profiles


def _infer_type(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    # For object dtype, try to detect datetime strings.
    # (infer_datetime_format was removed in pandas 3.0 — do not pass it.)
    if dtype == object:
        sample = series.dropna().head(20)
        if len(sample) > 0:
            try:
                pd.to_datetime(sample, errors="raise")
                return "datetime"
            except Exception:
                pass
    return "string"
