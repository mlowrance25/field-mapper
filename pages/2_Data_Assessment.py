import json
import pandas as pd
import streamlit as st

from utils.profiler import profile_dataframe
from utils.claude_client import call_claude_tool
from utils.prompt_builder import (
    ASSESSMENT_SYSTEM,
    ASSESSMENT_TOOL,
    build_assessment_prompt,
    reconcile_fields,
)

ASSESS_BATCH_SIZE = 8

st.set_page_config(page_title="Data Assessment — FieldMapper", layout="wide")
st.title("Data Assessment")

if "df" not in st.session_state:
    st.warning("No dataset loaded. Go to the **Upload** page first.")
    st.stop()

df = st.session_state["df"]
filename = st.session_state["filename"]
stem = filename.rsplit(".", 1)[0]
dataset_context = st.session_state.get("dataset_context", "")

st.caption(f"Dataset: **{filename}** — {len(df):,} rows × {len(df.columns)} columns")

# --- one-batch-per-rerun pipeline -------------------------------------------
# Each st.rerun() call restarts the script cleanly, keeping each API call
# inside its own short execution window and avoiding Streamlit timeouts.

if st.session_state.get("_assess_pending"):
    profiles = st.session_state["_assess_profiles"]
    idx = st.session_state["_assess_idx"]
    batches = [profiles[i:i + ASSESS_BATCH_SIZE] for i in range(0, len(profiles), ASSESS_BATCH_SIZE)]

    if idx < len(batches):
        batch = batches[idx]
        field_names = ", ".join(p["field_name"] for p in batch)
        with st.spinner(f"Assessing batch {idx+1}/{len(batches)}: {field_names}…"):
            prompt = build_assessment_prompt(batch, table_name=stem, dataset_context=dataset_context)
            result = call_claude_tool(ASSESSMENT_SYSTEM, prompt, ASSESSMENT_TOOL, "emit_assessment")
            st.session_state["_assess_results"].extend(result.get("fields", []))
            st.session_state["_assess_idx"] += 1
        st.rerun()
    else:
        fields = st.session_state.pop("_assess_results")
        st.session_state.pop("_assess_pending", None)
        st.session_state.pop("_assess_idx", None)
        st.session_state.pop("_assess_profiles", None)

        missing, extra = reconcile_fields(profiles, fields)
        if missing:
            st.error(f"Claude did not return {len(missing)} field(s): {', '.join(missing)}.")
        if extra:
            st.warning(f"Claude returned field(s) not in the dataset: {', '.join(extra)}.")

        st.session_state["assessment_result"] = fields
        st.session_state["assessment_profiles"] = {p["field_name"]: p for p in profiles}
        st.rerun()

if st.button("Run Assessment", type="primary"):
    profiles = profile_dataframe(df)
    st.session_state["_assess_pending"] = True
    st.session_state["_assess_idx"] = 0
    st.session_state["_assess_results"] = []
    st.session_state["_assess_profiles"] = profiles
    st.rerun()

if "assessment_result" in st.session_state:
    result = st.session_state["assessment_result"]
    profiles_map = st.session_state.get("assessment_profiles", {})

    # Join dictionary result if the Dictionary page has been run
    dict_map = {
        r["field_name"]: r
        for r in st.session_state.get("dictionary_result", [])
    }

    # ---------------------------------------------------------------------------
    # Helper functions
    # ---------------------------------------------------------------------------
    def compute_reliability(null_rate: float) -> str:
        if null_rate <= 0.05:
            return "Always Present"
        if null_rate <= 0.30:
            return "Usually Present"
        if null_rate <= 0.70:
            return "Sparse"
        return "Unreliable"

    def make_reliability_label(null_rate: float, missing_pct: float) -> str:
        if null_rate >= 0.99:
            return f"Empty · {missing_pct:.0f}% null"
        if null_rate <= 0.05:
            return "Always Present"
        if null_rate <= 0.30:
            return f"Usually Present · {missing_pct:.1f}% null"
        if null_rate <= 0.70:
            return f"Sparse · {missing_pct:.1f}% null"
        return f"Unreliable · {missing_pct:.1f}% null"

    def make_flags(row: dict, profile: dict, dict_entry: dict) -> str:
        flags = []
        if dict_entry.get("provenance") == "pipeline":
            flags.append("⚙ pipeline")
        null_rate = profile.get("null_rate", 0.0)
        if null_rate >= 0.99:
            flags.append("⚠ empty")
        if profile.get("inferred_type") == "float" and row.get("field_category") == "identifier":
            flags.append("⚠ type?")
        if dict_entry.get("confidence") == "low":
            flags.append("⚠ low conf")
        if row.get("is_classifier") and profile.get("cardinality", 0) > 20:
            flags.append("⚠ parse target")
        return "  ".join(flags)

    def make_relationships(row: dict) -> str:
        classifies = [v for v in (row.get("classifies") or []) if v]
        related = [v for v in (row.get("related_fields") or []) if v]
        parts = []
        if classifies:
            parts.append(f"gates {len(classifies)}")
        if related:
            parts.append(f"{len(related)} related")
        return "  ·  ".join(parts)

    # ---------------------------------------------------------------------------
    # Build triage table — 7 scannable columns, no prose
    # ---------------------------------------------------------------------------
    rows = []
    for r in result:
        fn = r.get("field_name", "")
        profile = profiles_map.get(fn, {})
        dict_entry = dict_map.get(fn, {})
        null_rate = profile.get("null_rate", 0.0)
        missing_pct = profile.get("missing_pct", 0.0)
        rows.append({
            "field_name":       fn,
            "type":             profile.get("inferred_type", ""),
            "category":         r.get("field_category", ""),
            "standard_mapping": "—",
            "conf":             "—",
            "reliability":      make_reliability_label(null_rate, missing_pct),
            "flags":            make_flags(r, profile, dict_entry),
            "relationships":    make_relationships(r),
        })
    display_df = pd.DataFrame(rows)

    total_rows = next(iter(profiles_map.values()), {}).get("total_rows", len(df))

    # Summary metrics
    total = len(result)
    flagged = sum(1 for r in display_df["flags"] if r and "⚠" in r)
    pipeline = sum(1 for r in display_df["flags"] if r and "⚙" in r)
    classifiers = sum(1 for r in result if r.get("is_classifier"))
    always_present = sum(
        1 for r in result
        if profiles_map.get(r.get("field_name"), {}).get("null_rate", 1.0) <= 0.05
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Records", f"{total_rows:,}")
    m2.metric("Total Fields", total)
    m3.metric("Needs Review ⚠", flagged)
    m4.metric("Pipeline Fields ⚙", pipeline)
    m5.metric("Classifiers", classifiers)

    st.divider()

    # Downloads — both use display_df so file and table are identical
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download CSV",
            data=display_df.to_csv(index=False),
            file_name=f"{stem}_assessment.csv",
            mime="text/csv",
        )
    with col2:
        st.download_button(
            "Download JSON",
            data=json.dumps(result, indent=2),
            file_name=f"{stem}_assessment.json",
            mime="application/json",
        )

    st.divider()

    st.dataframe(
        display_df,
        use_container_width=True,
        height=500,
        column_config={
            "field_name":       st.column_config.TextColumn("Field", width="medium"),
            "type":             st.column_config.TextColumn("Type", width="small"),
            "category":         st.column_config.TextColumn("Category", width="small"),
            "standard_mapping": st.column_config.TextColumn("Standard Mapping", width="medium"),
            "conf":             st.column_config.TextColumn("Conf", width="small"),
            "reliability":      st.column_config.TextColumn("Reliability", width="medium"),
            "flags":            st.column_config.TextColumn("Flags", width="medium"),
            "relationships":    st.column_config.TextColumn("Relationships", width="small"),
        },
    )

    st.divider()

    # ---------------------------------------------------------------------------
    # Value Distribution
    # ---------------------------------------------------------------------------
    st.subheader("Value Distribution")

    dist_field = st.selectbox(
        "Select a field",
        ["— select —"] + [r.get("field_name", "") for r in result],
        key="dist_field_select",
    )

    if dist_field and dist_field != "— select —":
        series = df[dist_field].dropna()
        value_counts = series.value_counts()
        n_unique = len(value_counts)

        freq_df = pd.DataFrame({
            "Value": value_counts.index.astype(str),
            "Count": value_counts.values,
            "% of rows": (value_counts.values / len(df) * 100).round(1),
        })

        if n_unique <= 10:
            st.dataframe(freq_df, use_container_width=True, hide_index=True)
        else:
            st.dataframe(freq_df.head(10), use_container_width=True, hide_index=True)
            with st.expander(f"Show all {n_unique} values"):
                st.dataframe(freq_df, use_container_width=True, hide_index=True)

    st.divider()

    field_names = [r.get("field_name", "") for r in result]
    selected_field = st.selectbox("Edit a field", ["— select —"] + field_names)

    if selected_field and selected_field != "— select —":
        idx = field_names.index(selected_field)
        row = result[idx]
        field_name = selected_field

        st.subheader(f"Edit: `{field_name}`")

        profile = profiles_map.get(field_name, {})
        reliability = compute_reliability(profile.get("null_rate", 0.0))
        dict_entry = dict_map.get(field_name, {})

        with st.form(key=f"edit_{field_name}"):
            st.caption(f"Reliability: **{reliability}** · {profile.get('num_present', '')} present · {profile.get('missing_pct', 0):.1f}% missing")

            e_description = st.text_area(
                "Description",
                value=dict_entry.get("description", ""),
                height=80,
            )

            PROVENANCE_OPTS = ["source", "pipeline", "unknown"]
            CATEGORY_OPTS = ["identifier", "classifier", "measure", "descriptor", "flag", "date"]

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                prov_val = dict_entry.get("provenance") or "unknown"
                e_provenance = st.selectbox(
                    "Provenance",
                    PROVENANCE_OPTS,
                    index=PROVENANCE_OPTS.index(prov_val) if prov_val in PROVENANCE_OPTS else 2,
                )
            with col_b:
                cat_val = row.get("field_category") or "descriptor"
                e_category = st.selectbox(
                    "Field Category",
                    CATEGORY_OPTS,
                    index=CATEGORY_OPTS.index(cat_val) if cat_val in CATEGORY_OPTS else 3,
                )
            with col_c:
                e_is_classifier = st.checkbox("Is Classifier", value=bool(row.get("is_classifier")))

            e_classifies = st.text_input(
                "Classifies (comma-separated field names)",
                value=", ".join(row.get("classifies") or []),
            )
            e_related = st.text_input(
                "Related Fields (comma-separated field names)",
                value=", ".join(row.get("related_fields") or []),
            )

            if st.form_submit_button("Save Changes", type="primary"):
                # Update assessment result
                result[idx]["field_category"] = e_category
                result[idx]["is_classifier"] = e_is_classifier
                result[idx]["classifies"] = [s.strip() for s in e_classifies.split(",") if s.strip()]
                result[idx]["related_fields"] = [s.strip() for s in e_related.split(",") if s.strip()]
                st.session_state["assessment_result"] = result

                # Update dictionary result if it exists
                dict_result = st.session_state.get("dictionary_result", [])
                for i, d in enumerate(dict_result):
                    if d.get("field_name") == field_name:
                        dict_result[i]["description"] = e_description
                        dict_result[i]["provenance"] = e_provenance
                        break
                else:
                    if e_description:
                        dict_result.append({
                            "field_name": field_name,
                            "description": e_description,
                            "provenance": e_provenance,
                        })
                if dict_result:
                    st.session_state["dictionary_result"] = dict_result

                st.rerun()

        if profile.get("distinct_values"):
            vals = profile["distinct_values"]
            st.caption(f"Distinct values ({len(vals)}): {', '.join(vals)}")

        with st.expander("Raw field profile"):
            st.json({k: v for k, v in profile.items() if v is not None and v != []})

    st.caption("AI-generated output. Human review recommended before use in production.")
