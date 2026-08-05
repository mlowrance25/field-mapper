import pandas as pd


def parse_json(raw) -> tuple[pd.DataFrame, list[str]]:
    """Flatten one level of JSON nesting into a DataFrame.

    Returns (df, nested_columns) rather than warning directly — callers
    decide how to surface nested_columns (a Streamlit toast, an MCP tool
    response field, etc.), since this module has no UI of its own.
    """
    if isinstance(raw, list):
        df = pd.json_normalize(raw, max_level=1)
    elif isinstance(raw, dict):
        records = next((v for v in raw.values() if isinstance(v, list)), None)
        if records is not None:
            df = pd.json_normalize(records, max_level=1)
        else:
            df = pd.json_normalize([raw], max_level=1)
    else:
        raise ValueError("Unsupported JSON structure.")

    return df, find_nested_columns(df)


def find_nested_columns(df: pd.DataFrame) -> list[str]:
    return [
        col for col in df.columns
        if df[col].apply(lambda x: isinstance(x, (dict, list))).any()
    ]
