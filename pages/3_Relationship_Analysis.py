import json

import pandas as pd
import streamlit as st

from utils.cardinality import analyze_cardinality
from utils.completeness import analyze_completeness_batch
from utils.coverage import evaluate_coverage, validate_expression

st.set_page_config(page_title="Relationship Analysis — FieldMapper", layout="wide")
st.title("Relationship Analysis")

if "df" not in st.session_state:
    st.warning("No dataset loaded. Go to the **Upload** page first.")
    st.stop()

df = st.session_state["df"]
filename = st.session_state["filename"]
stem = filename.rsplit(".", 1)[0]
columns = df.columns.tolist()

st.caption(f"Dataset: **{filename}** — {len(df):,} rows × {len(df.columns)} columns")


def _tokens_to_expr(tokens: list[str]) -> str:
    """Assemble a click-built token list into the AND/OR expression string
    that utils.coverage understands — same spacing convention its tokenizer
    produces, so it round-trips cleanly.
    """
    return " ".join(tokens).replace("( ", "(").replace(" )", ")")


def render_cardinality_results(df, stem):
    result = st.session_state["_rel_result"]
    expectation = st.session_state.get("_rel_expectation")

    field_a = result["field_a"]
    field_b = result["field_b"]

    # Primary display always follows the declared direction (or A→B by default)
    if expectation and expectation["direction"] == "B→A":
        primary_table = result["mapping_table_ba"]
        primary_key, primary_val = field_b, field_a
        conf = result["conformance_ba"]
        viol_count = result["violation_count_ba"]
        distinct_key = result["distinct_b"]
        info_viol = result["violation_count_ab"]
        info_distinct = result["distinct_a"]
        info_conf = result["conformance_ab"]
        info_key, info_val = field_a, field_b
    else:
        primary_table = result["mapping_table_ab"]
        primary_key, primary_val = field_a, field_b
        conf = result["conformance_ab"]
        viol_count = result["violation_count_ab"]
        distinct_key = result["distinct_a"]
        info_viol = result["violation_count_ba"]
        info_distinct = result["distinct_b"]
        info_conf = result["conformance_ba"]
        info_key, info_val = field_b, field_a

    # Resolve alarms based on direction + expected shape.
    # The constraint side depends on shape — not every direction violation is an alarm.
    # Example: for 1-to-many A→B, A having many B values is expected;
    # the constraint is that B values should each map back to only one A.
    alarm_set = set()
    alarm_key = alarm_val = alarm_finding = None

    if expectation:
        _dir = expectation["direction"]
        _shape = expectation["shape"]

        if _shape == "many-to-many":
            pass  # no constraint — no alarms possible

        elif _dir == "A→B":
            if _shape in ("1-to-1", "many-to-1"):
                # Constraint: each A maps to exactly one B
                alarm_set = set(result["violations_ab"])
                alarm_key, alarm_val = field_a, field_b
                alarm_finding = f"`{field_a}` values that map to more than one `{field_b}`"
            elif _shape == "1-to-many":
                # A→many B is expected; constraint is B belongs to only one A
                alarm_set = set(result["violations_ba"])
                alarm_key, alarm_val = field_b, field_a
                alarm_finding = f"`{field_b}` values that appear under more than one `{field_a}`"

        else:  # B→A
            if _shape in ("1-to-1", "many-to-1"):
                # Constraint: each B maps to exactly one A
                alarm_set = set(result["violations_ba"])
                alarm_key, alarm_val = field_b, field_a
                alarm_finding = f"`{field_b}` values that map to more than one `{field_a}`"
            elif _shape == "1-to-many":
                # B→many A is expected; constraint is A belongs to only one B
                alarm_set = set(result["violations_ab"])
                alarm_key, alarm_val = field_a, field_b
                alarm_finding = f"`{field_a}` values that appear under more than one `{field_b}`"

    shape = result["dominant_shape"] or "indeterminate"

    # No usable rows
    if result["working_rows"] == 0:
        st.warning(
            f"No rows with non-null values in both `{field_a}` and `{field_b}`. "
            "Cannot compute mapping shape."
        )
        st.caption(
            f"Null `{field_a}`: {result['null_a']:,} rows · "
            f"Null `{field_b}`: {result['null_b']:,} rows · "
            f"Total: {result['total_rows']:,} rows"
        )
        return

    # Summary banner
    st.subheader(f"`{field_a}` ↔ `{field_b}`")
    st.markdown(
        f"**{shape}** ({conf:.1%}; "
        f"{viol_count} of {distinct_key} distinct `{primary_key}` values "
        f"map to more than one `{primary_val}`)"
    )

    excluded = result["total_rows"] - result["working_rows"]
    if excluded > 0:
        st.caption(
            f"Coverage: {result['working_rows']:,} of {result['total_rows']:,} rows used — "
            f"{result['null_a']:,} null `{field_a}`, "
            f"{result['null_b']:,} null `{field_b}` excluded"
        )

    # Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Rows", f"{result['total_rows']:,}")
    m2.metric("Working Rows", f"{result['working_rows']:,}")
    m3.metric(f"Distinct {field_a}", result["distinct_a"])
    m4.metric(f"Distinct {field_b}", result["distinct_b"])
    m5.metric("A→B Violations", result["violation_count_ab"])

    st.divider()

    # -------------------------------------------------------------------
    # Set Expectation
    # -------------------------------------------------------------------
    st.subheader("Set Expectation")
    st.caption("Optional — declare what you expect from this mapping to surface violations as alarms.")

    DIRECTION_OPTS = [f"A→B  ({field_a} → {field_b})", f"B→A  ({field_b} → {field_a})"]
    SHAPE_OPTS = ["1-to-1", "1-to-many", "many-to-1", "many-to-many"]

    cur_dir_idx = 0
    cur_shape_idx = 0
    if expectation:
        cur_dir_idx = 0 if expectation["direction"] == "A→B" else 1
        cur_shape_idx = SHAPE_OPTS.index(expectation["shape"]) if expectation["shape"] in SHAPE_OPTS else 0

    with st.form("expectation"):
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            direction_sel = st.selectbox("Declared direction", DIRECTION_OPTS, index=cur_dir_idx)
        with col_e2:
            shape_sel = st.selectbox("Expected shape", SHAPE_OPTS, index=cur_shape_idx)
        apply = st.form_submit_button("Apply Expectation", type="primary")

    if apply:
        direction = "A→B" if direction_sel.startswith("A→B") else "B→A"
        st.session_state["_rel_expectation"] = {"direction": direction, "shape": shape_sel}
        st.rerun()

    if expectation:
        if st.button("Clear Expectation"):
            st.session_state["_rel_expectation"] = None
            st.rerun()

    # Alarm panel — rows from the dataset that violate the declared constraint
    if alarm_set:
        st.error(f"**{len(alarm_set)} constraint violation(s) — {alarm_finding}**")
        violating_rows = (
            df[df[alarm_key].isin(alarm_set)][[alarm_key, alarm_val]]
            .drop_duplicates()
            .sort_values([alarm_key, alarm_val])
            .reset_index(drop=True)
        )
        st.dataframe(violating_rows, use_container_width=True, hide_index=True)

    st.divider()

    # -------------------------------------------------------------------
    # Mapping table
    # -------------------------------------------------------------------
    st.subheader(f"Mapping: `{primary_key}` → `{primary_val}`")

    filter_text = st.text_input(
        f"Filter by {primary_key}",
        placeholder="e.g. parking, regulatory…",
        label_visibility="collapsed",
    )

    filtered_table = [
        r for r in primary_table
        if not filter_text or filter_text.lower() in str(r["key_value"]).lower()
    ]

    display_rows = [
        {
            primary_key: r["key_value"],
            f"{primary_val} values": ", ".join(r["mapped_values"]),
            "fan_out": r["fan_out"],
            "": "⚠" if r["key_value"] in alarm_set else "",
        }
        for r in filtered_table
    ]
    display_df = pd.DataFrame(display_rows)
    table_height = min(500, 35 * len(display_rows) + 38)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "fan_out": st.column_config.NumberColumn("Fan-out", width="small"),
            "": st.column_config.TextColumn("", width="small"),
        },
        height=table_height,
    )

    # Informational: reverse direction
    with st.expander(f"Informational — reverse direction (`{info_key}` → `{info_val}`)"):
        if info_viol == 0:
            st.write(f"No violations. `{info_key}` → `{info_val}` direction is clean.")
        else:
            st.write(
                f"{info_viol} of {info_distinct} distinct `{info_key}` values "
                f"map to more than one `{info_val}` ({info_conf:.1%} conformance). "
                "Informational only — no alarms raised for this direction."
            )

    st.divider()

    # -------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------
    field_a_safe = field_a.replace(" ", "_")
    field_b_safe = field_b.replace(" ", "_")
    file_stem = f"{stem}_mapping_{field_a_safe}_to_{field_b_safe}"

    flat_csv = pd.DataFrame([
        {
            primary_key: r["key_value"],
            f"{primary_val}_values": ";".join(r["mapped_values"]),
            "fan_out": r["fan_out"],
            "is_alarm": r["key_value"] in alarm_set,
        }
        for r in primary_table
    ]).to_csv(index=False)

    export_json = dict(result)
    export_json["alarms"] = list(alarm_set)
    export_json["expectation"] = expectation

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "Download CSV",
            data=flat_csv,
            file_name=f"{file_stem}.csv",
            mime="text/csv",
        )
    with col_dl2:
        st.download_button(
            "Download JSON",
            data=json.dumps(export_json, indent=2, default=str),
            file_name=f"{file_stem}.json",
            mime="application/json",
        )

    st.caption("All metrics computed deterministically from the dataset. No LLM in the compute path.")


def render_completeness_comparison(stem):
    batch = st.session_state["_comp_batch_result"]

    st.subheader("Completeness Comparison")
    st.caption(
        f"{len(batch)} unit(s) analyzed · single-column units first, then multi-column units."
    )

    table_rows = []
    for r in batch:
        is_single = len(r["columns"]) == 1
        table_rows.append({
            "Unit": r["name"],
            "Columns": len(r["columns"]),
            "Total Rows": f"{r['total_rows']:,}",
            "Complete": f"{r['complete_count']:,}",
            "Complete %": f"{r['complete_rate']:.1%}",
            "Partial": "—" if is_single else f"{r['partial_count']:,}",
            "Partial %": "—" if is_single else f"{r['partial_rate']:.1%}",
            "Empty": f"{r['empty_count']:,}",
            "Empty %": f"{r['empty_rate']:.1%}",
        })
    comparison_df = pd.DataFrame(table_rows)
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------
    # Per-unit detail — multi-column units only; single-column units can
    # never have partial rows, so there's nothing to expand into.
    # -------------------------------------------------------------------
    multi_results = [r for r in batch if len(r["columns"]) > 1]
    if multi_results:
        st.divider()
        st.subheader("Partial Row Detail")
        for r in multi_results:
            partial_rows = sorted(r["partial_rows"], key=lambda p: len(p["missing"]), reverse=True)
            label = f"`{r['name']}` — {len(partial_rows)} partial row(s)"
            with st.expander(label):
                if not partial_rows:
                    st.write("No partial rows.")
                    continue
                partial_table = pd.DataFrame([
                    {
                        "row_index": p["index"],
                        "missing_columns": ", ".join(p["missing"]),
                        "missing_count": len(p["missing"]),
                    }
                    for p in partial_rows
                ])
                table_height = min(400, 35 * len(partial_table) + 38)
                st.dataframe(partial_table, use_container_width=True, hide_index=True, height=table_height)

                st.caption("Missing pattern breakdown")
                pattern_table = pd.DataFrame(
                    [{"missing": k, "rows": v} for k, v in r["missing_patterns"].items()]
                ).sort_values("rows", ascending=False)
                st.dataframe(pattern_table, use_container_width=True, hide_index=True)

    st.divider()

    # -------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------
    csv_rows = []
    for r in batch:
        is_single = len(r["columns"]) == 1
        csv_rows.append({
            "unit": r["name"],
            "columns": len(r["columns"]),
            "total_rows": r["total_rows"],
            "complete": r["complete_count"],
            "complete_pct": round(r["complete_rate"] * 100, 1),
            "partial": "" if is_single else r["partial_count"],
            "partial_pct": "" if is_single else round(r["partial_rate"] * 100, 1),
            "empty": r["empty_count"],
            "empty_pct": round(r["empty_rate"] * 100, 1),
        })
    export_csv = pd.DataFrame(csv_rows).to_csv(index=False)
    export_json = json.dumps(batch, indent=2, default=str)

    file_stem = f"{stem}_completeness_comparison"
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "Download CSV",
            data=export_csv,
            file_name=f"{file_stem}.csv",
            mime="text/csv",
            key="_comp_dl_csv",
        )
    with col_dl2:
        st.download_button(
            "Download JSON",
            data=export_json,
            file_name=f"{file_stem}.json",
            mime="application/json",
            key="_comp_dl_json",
        )

    st.caption("All metrics computed deterministically from the dataset. No LLM in the compute path.")


def render_coverage_results(stem):
    print("About to render coverage results")
    result = st.session_state["_coverage_result"]

    st.subheader("Coverage Results")
    table_rows = [
        {
            "Expression": r["expression"],
            "Rows Satisfied": f"{r['rows_satisfied']:,}",
            "%": f"{r['rate']:.1%}",
        }
        for r in result
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.divider()

    csv_rows = [
        {
            "expression": r["expression"],
            "rows_satisfied": r["rows_satisfied"],
            "rate_pct": round(r["rate"] * 100, 1),
        }
        for r in result
    ]
    export_csv = pd.DataFrame(csv_rows).to_csv(index=False)
    export_json = json.dumps(result, indent=2, default=str)

    file_stem = f"{stem}_coverage_expressions"
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "Download CSV",
            data=export_csv,
            file_name=f"{file_stem}.csv",
            mime="text/csv",
            key="_cov_dl_csv",
        )
    with col_dl2:
        st.download_button(
            "Download JSON",
            data=export_json,
            file_name=f"{file_stem}.json",
            mime="application/json",
            key="_cov_dl_json",
        )

    st.caption("All metrics computed deterministically from the dataset. No LLM in the compute path.")


# ---------------------------------------------------------------------------
# Relation type — lives outside any form so switching it reactively changes
# which declaration UI is shown below (Streamlit forms can't conditionally
# reveal fields based on in-form selections).
# ---------------------------------------------------------------------------
REL_TYPES = ["cardinality", "completeness"]
prior_type = st.session_state.get("_rel_type", "cardinality")
rel_type = st.selectbox("Relation type", REL_TYPES, index=REL_TYPES.index(prior_type))

if rel_type != prior_type:
    st.session_state.pop("_rel_result", None)
    st.session_state.pop("_rel_expectation", None)
    st.session_state.pop("_comp_units", None)
    st.session_state.pop("_comp_unit_seq", None)
    st.session_state.pop("_comp_batch_result", None)
    st.session_state.pop("_coverage_expressions", None)
    st.session_state.pop("_coverage_expr_seq", None)
    st.session_state.pop("_coverage_result", None)
st.session_state["_rel_type"] = rel_type

# ---------------------------------------------------------------------------
# Declaration form
# ---------------------------------------------------------------------------
if rel_type == "cardinality":
    prior_a = st.session_state.get("_rel_field_a", columns[0])
    prior_b = st.session_state.get("_rel_field_b", columns[min(1, len(columns) - 1)])
    idx_a = columns.index(prior_a) if prior_a in columns else 0
    idx_b = columns.index(prior_b) if prior_b in columns else min(1, len(columns) - 1)

    with st.form("declaration"):
        st.subheader("Declare a field pair")
        col_a, col_b = st.columns(2)
        with col_a:
            field_a = st.selectbox("Field A", columns, index=idx_a)
        with col_b:
            field_b = st.selectbox("Field B", columns, index=idx_b)
        submitted = st.form_submit_button("Analyze Mapping", type="primary")

    if submitted:
        if field_a == field_b:
            st.error("Field A and Field B must be different fields.")
            st.stop()
        with st.spinner(f"Analyzing `{field_a}` ↔ `{field_b}`…"):
            result = analyze_cardinality(df, field_a, field_b)
        st.session_state["_rel_result"] = result
        st.session_state["_rel_field_a"] = field_a
        st.session_state["_rel_field_b"] = field_b
        st.session_state.pop("_rel_expectation", None)
        st.rerun()

elif rel_type == "completeness":
    # Dynamic add/remove rows can't live inside st.form — Streamlit forms
    # only rerun on submit, so Add/Remove buttons need immediate reruns.
    if "_comp_units" not in st.session_state:
        st.session_state["_comp_units"] = [{"id": 0, "columns": []}]
        st.session_state["_comp_unit_seq"] = 1

    st.subheader("Declare units")
    st.caption(
        "Add one or more units (1+ columns each) to compare completeness across them in a single pass."
    )

    comp_units = st.session_state["_comp_units"]
    remove_id = None
    for i, u in enumerate(comp_units):
        col_pick, col_remove = st.columns([6, 1])
        with col_pick:
            selected = st.multiselect(
                f"Unit {i + 1} columns",
                columns,
                default=[c for c in u["columns"] if c in columns],
                key=f"_comp_unit_cols_{u['id']}",
            )
            u["columns"] = selected
        with col_remove:
            st.write("")
            if st.button("Remove", key=f"_comp_unit_remove_{u['id']}", disabled=len(comp_units) == 1):
                remove_id = u["id"]

    if remove_id is not None:
        st.session_state["_comp_units"] = [u for u in comp_units if u["id"] != remove_id]
        st.rerun()

    col_add, col_analyze = st.columns([1, 3])
    with col_add:
        if st.button("+ Add unit"):
            new_id = st.session_state["_comp_unit_seq"]
            st.session_state["_comp_unit_seq"] += 1
            st.session_state["_comp_units"].append({"id": new_id, "columns": []})
            st.rerun()
    with col_analyze:
        analyze_clicked = st.button("Analyze Completeness", type="primary")

    if analyze_clicked:
        print(f"Analyze Button Clicked {'-'*100}")
        declared = [u for u in st.session_state["_comp_units"] if u["columns"]]
        print(f"Declared {len(declared)} columns")
        print(declared)
        if not declared:
            st.error("Declare at least one unit with 1 or more columns before analyzing.")
            st.stop()
        unit_specs = [{"name": " + ".join(u["columns"]), "columns": u["columns"]} for u in declared]
        with st.spinner(f"Analyzing {len(unit_specs)} declared unit(s)…"):
            comp_batch = analyze_completeness_batch(df, unit_specs)
        st.session_state["_comp_batch_result"] = comp_batch
        st.rerun()

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
if rel_type == "cardinality" and "_rel_result" in st.session_state:
    render_cardinality_results(df, stem)
elif rel_type == "completeness":
    if "_comp_batch_result" in st.session_state:
        st.divider()
        render_completeness_comparison(stem)
    else:
        st.info("Declare at least one unit above and click **Analyze Completeness** to see results.")

    # -----------------------------------------------------------------
    # Section 2: Coverage Expressions — separate section, separate state,
    # separate results table. Reuses units declared above as terms; never
    # merges with Section 1's table.
    # -----------------------------------------------------------------
    st.divider()
    st.subheader("Coverage Expressions")
    st.caption(
        "Author AND/OR expressions over the units declared above to see how many records "
        "satisfy an outcome through any available path. One level of parentheses; no NOT."
    )

    live_declared = [u for u in st.session_state.get("_comp_units", []) if u["columns"]]
    if not live_declared:
        st.info("Declare at least one unit above first — coverage expressions reuse those units as terms.")
    else:
        unit_specs = [{"name": " + ".join(u["columns"]), "columns": u["columns"]} for u in live_declared]
        available_units = {
            r["name"]: r["columns"] for r in analyze_completeness_batch(df, unit_specs)
        }
        st.caption("Available terms: " + ", ".join(f"`{n}`" for n in available_units))

        if "_coverage_expressions" not in st.session_state:
            st.session_state["_coverage_expressions"] = [{"id": 0, "tokens": []}]
            st.session_state["_coverage_expr_seq"] = 1

        cov_exprs = st.session_state["_coverage_expressions"]
        remove_expr_id = None
        term_names = list(available_units.keys())
        for i, e in enumerate(cov_exprs):
            st.markdown(f"**Expression {i + 1}**")
            col_mode, col_pick, col_add, col_back, col_clear, col_rm = st.columns([1.4, 2.4, 0.7, 0.7, 0.7, 0.9])
            with col_mode:
                mode = st.segmented_control(
                    "Mode",
                    ["Field", "Operator"],
                    default="Field",
                    key=f"_cov_mode_{e['id']}",
                    label_visibility="collapsed",
                )
            with col_pick:
                if mode == "Operator":
                    choice = st.selectbox(
                        "Operator",
                        ["AND", "OR", "(", ")"],
                        key=f"_cov_operator_{e['id']}",
                        label_visibility="collapsed",
                    )
                else:
                    choice = st.selectbox(
                        "Field",
                        term_names,
                        key=f"_cov_field_{e['id']}",
                        label_visibility="collapsed",
                    )
            with col_add:
                st.write("")
                if st.button("Add", key=f"_cov_add_{e['id']}") and choice:
                    e["tokens"].append(choice)
                    st.rerun()
            with col_back:
                st.write("")
                if st.button(":material/backspace:", key=f"_cov_back_{e['id']}", disabled=not e["tokens"]):
                    e["tokens"].pop()
                    st.rerun()
            with col_clear:
                st.write("")
                if st.button("Clear", key=f"_cov_clear_{e['id']}", disabled=not e["tokens"]):
                    e["tokens"] = []
                    st.rerun()
            with col_rm:
                st.write("")
                if st.button("Remove", key=f"_cov_expr_remove_{e['id']}", disabled=len(cov_exprs) == 1):
                    remove_expr_id = e["id"]

            expr_str = _tokens_to_expr(e["tokens"])
            st.code(expr_str or "(no tokens yet — pick a field or operator above and click Add)", language=None)
            if expr_str.strip():
                try:
                    validate_expression(expr_str, available_units)
                except ValueError as ve:
                    st.caption(f":warning: {ve}")

        if remove_expr_id is not None:
            st.session_state["_coverage_expressions"] = [e for e in cov_exprs if e["id"] != remove_expr_id]
            st.rerun()

        col_add_expr, col_analyze_expr = st.columns([1, 3])
        with col_add_expr:
            if st.button("+ Add expression"):
                new_id = st.session_state["_coverage_expr_seq"]
                st.session_state["_coverage_expr_seq"] += 1
                st.session_state["_coverage_expressions"].append({"id": new_id, "tokens": []})
                st.rerun()
        with col_analyze_expr:
            analyze_expr_clicked = st.button("Analyze Coverage", type="primary")

        if analyze_expr_clicked:
            declared_exprs = [
                s for e in st.session_state["_coverage_expressions"]
                if (s := _tokens_to_expr(e["tokens"]).strip())
            ]
            if not declared_exprs:
                st.error("Declare at least one expression before analyzing.")
                st.stop()
            try:
                with st.spinner(f"Evaluating {len(declared_exprs)} expression(s)…"):
                    coverage_result = evaluate_coverage(df, available_units, declared_exprs)
                st.session_state["_coverage_result"] = coverage_result
            except ValueError as ve:
                st.error(f"Could not evaluate expressions: {ve}")
                st.stop()
            st.rerun()

        if "_coverage_result" in st.session_state:
            st.divider()
            render_coverage_results(stem)