import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from utils.ingest import parse_json

load_dotenv()

st.set_page_config(page_title="FieldMapper", layout="wide")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("FieldMapper")
st.caption("Upload a dataset to generate a data dictionary or run a data assessment.")

uploaded_file = st.file_uploader("Upload Dataset", type=["csv", "json"])

if uploaded_file is not None:
    if st.session_state.get("filename") != uploaded_file.name:
        for key in [
            "df", "filename",
            "dictionary_result", "assessment_result", "assessment_profiles",
        ]:
            st.session_state.pop(key, None)

    if "df" not in st.session_state:
        size_mb = uploaded_file.size / (1024 * 1024)

        if size_mb > 50:
            st.error(f"File is {size_mb:.1f}MB — exceeds the 50MB limit. Please upload a smaller file.")
            st.stop()

        if size_mb > 10:
            st.warning(f"File is {size_mb:.1f}MB — large files may take longer to process.")

        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            else:
                raw = json.load(uploaded_file)
                df, nested_cols = parse_json(raw)
                if nested_cols:
                    st.warning(
                        f"Deeply nested fields detected: `{'`, `'.join(nested_cols)}`. "
                        "Only one level of nesting was flattened — nested values in these columns are shown as-is."
                    )

            if df.empty:
                st.warning("The uploaded file contains no rows. Please upload a file with data.")
                st.stop()

            st.session_state["df"] = df
            st.session_state["filename"] = uploaded_file.name

        except Exception as e:
            st.error(f"Could not parse file: {e}")
            st.stop()

if "df" in st.session_state:
    df = st.session_state["df"]

    st.text_area(
        "Dataset context (optional, recommended)",
        key="dataset_context",
        placeholder=(
            "e.g. Asset inventory export from a work order system; each row is one asset. "
            "Mention the source system, domain, and what each row represents."
        ),
        help=(
            "Provided to Claude to ground field descriptions. Leave blank to let it infer "
            "(descriptions will be flagged lower-confidence)."
        ),
    )

    st.success(f"Loaded **{st.session_state['filename']}** — {len(df):,} rows × {len(df.columns)} columns")

    tab_sample, = st.tabs(["Data Sample"])
    with tab_sample:
        selected_cols = st.multiselect(
            "Columns",
            options=df.columns.tolist(),
            default=df.columns.tolist(),
            label_visibility="collapsed",
        )
        if selected_cols:
            st.dataframe(df[selected_cols], use_container_width=True)
        else:
            st.info("Select at least one column to display.")

    st.info("Use the sidebar to navigate to **Data Dictionary** or **Data Assessment**.")

else:
    st.info("Upload a CSV or JSON file to get started.")
