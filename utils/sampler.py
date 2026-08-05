# NOTE: Not currently imported by any page. Retained for a future "send sample
# rows" path — e.g. if a prompt needs raw row data alongside the field profile.
# If that path is never built, this file can be deleted.

import pandas as pd
import streamlit as st

SAMPLE_HEAD = 100
SAMPLE_RANDOM = 100
MAX_ROWS_BEFORE_SAMPLING = 200
TOKEN_BUDGET = 80_000
CHARS_PER_TOKEN = 4


def sample_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """
    Return a representative sample of df for use in prompts.
    Returns (sampled_df, was_sampled).
    """
    if len(df) <= MAX_ROWS_BEFORE_SAMPLING:
        return df, False

    head = df.head(SAMPLE_HEAD)
    remaining = df.iloc[SAMPLE_HEAD:]
    random_sample = remaining.sample(min(SAMPLE_RANDOM, len(remaining)), random_state=42)
    sampled = pd.concat([head, random_sample]).reset_index(drop=True)
    return sampled, True


def build_prompt_data(df: pd.DataFrame) -> tuple[str, bool, bool]:
    """
    Convert a DataFrame to a compact CSV string for prompt inclusion.
    Applies sampling first, then truncates rows if token budget is exceeded.
    Returns (csv_string, was_sampled, was_truncated).
    """
    sampled, was_sampled = sample_dataframe(df)

    csv_str = sampled.to_csv(index=False)
    estimated_tokens = len(csv_str) / CHARS_PER_TOKEN

    was_truncated = False
    if estimated_tokens > TOKEN_BUDGET:
        # Truncate rows until within budget
        for n_rows in range(len(sampled), 0, -10):
            csv_str = sampled.head(n_rows).to_csv(index=False)
            if len(csv_str) / CHARS_PER_TOKEN <= TOKEN_BUDGET:
                was_truncated = True
                break

    return csv_str, was_sampled, was_truncated


def show_sampling_notice(was_sampled: bool, was_truncated: bool):
    if was_truncated:
        st.warning(
            "Dataset is very large — sample was truncated to fit within the token budget. "
            "Results reflect a subset of rows."
        )
    elif was_sampled:
        st.info(
            f"Dataset sampled: first {SAMPLE_HEAD} rows + {SAMPLE_RANDOM} random rows sent to Claude. "
            "All column headers included."
        )
