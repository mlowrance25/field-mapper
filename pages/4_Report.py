import json

import pandas as pd
import streamlit as st

from utils.findings import export_metadata, init_report_findings

st.set_page_config(page_title="Report — FieldMapper", layout="wide")
st.title("Pre-Ingestion Findings Report")

init_report_findings()
findings = st.session_state["_report_findings"]

if not findings:
    st.info(
        "No findings in report yet. Run an analysis and click **Add to Report**."
    )
    st.stop()

col_title, col_clear = st.columns([4, 1])
with col_title:
    dataset_names = sorted({f.get("dataset", "unknown") for f in findings})
    st.caption(f"{len(findings)} finding(s) · dataset(s): {', '.join(dataset_names)}")
with col_clear:
    if st.button("Clear Report", type="secondary"):
        st.session_state["_report_findings"] = []
        st.rerun()


def _summary_for(f: dict) -> str:
    ft = f["finding_type"]
    if ft == "cardinality":
        m = f["metrics"]
        return (
            f"{m['dominant_shape']} ({m['conf']:.1%}; {m['viol_count']} of "
            f"{m['distinct_key']} distinct values map to more than one)"
        )
    if ft == "completeness":
        return f"{len(f['units'])} unit(s) compared"
    if ft == "coverage":
        return f"{len(f['results'])} expression(s) evaluated"
    if ft == "value_distribution":
        return f"{f['field']}: {f['n_unique']} distinct values"
    return ""


# ---------------------------------------------------------------------------
# Export — above the findings cards so it's reachable without scrolling
# through a potentially long report.
# ---------------------------------------------------------------------------
_meta = export_metadata()

_csv_rows = [
    {
        "finding_id": f["finding_id"],
        "added_at": f["added_at"],
        "finding_type": f["finding_type"],
        "dataset": f.get("dataset", _meta["dataset"]),
        "notes": f.get("notes", ""),
        "summary": _summary_for(f),
        "generated_at": _meta["generated_at"],
        "tool_version": _meta["tool_version"],
    }
    for f in findings
]
_export_csv = pd.DataFrame(_csv_rows).to_csv(index=False)
_export_json = json.dumps({"report_metadata": _meta, "findings": findings}, indent=2, default=str)

_dataset_name = _meta["dataset"]
_file_stem = _dataset_name.rsplit(".", 1)[0] if _dataset_name != "unknown" else "fieldmapper_report"

col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    st.download_button(
        "Download CSV",
        data=_export_csv,
        file_name=f"{_file_stem}_report.csv",
        mime="text/csv",
    )
with col_dl2:
    st.download_button(
        "Download JSON",
        data=_export_json,
        file_name=f"{_file_stem}_report.json",
        mime="application/json",
    )

st.divider()

ROW_CAP = 50


def _capped(rows: list[dict], cap: int = ROW_CAP) -> tuple[pd.DataFrame, int]:
    total = len(rows)
    return pd.DataFrame(rows[:cap]), total


def _render_field_descriptions(field_descriptions: dict, llm_confidence: dict, status: str) -> None:
    """Shared rendering for field-description enrichment across all finding
    types. `llm_confidence` is always labeled explicitly as an LLM self-
    assessment — never implied to be human-reviewed, since no such signal
    exists anywhere in Data Dictionary today.
    """
    if status == "not_run":
        st.caption("Data Dictionary not run — no field descriptions available.")
        return

    available = {k: v for k, v in field_descriptions.items() if v}
    missing = [k for k, v in field_descriptions.items() if not v]

    if status == "partial" and missing:
        st.caption(
            f"Data Dictionary run, but doesn't cover {len(missing)} of "
            f"{len(field_descriptions)} referenced field(s): {', '.join(missing)}"
        )

    for name, desc in available.items():
        conf = llm_confidence.get(name)
        conf_label = f" — *{conf} confidence, LLM-generated, not human-reviewed*" if conf else ""
        st.markdown(f"**`{name}`**: {desc}{conf_label}")


def _render_notes(notes: str) -> None:
    if notes and notes.strip():
        st.info(f"📝 {notes}")


def _render_cardinality(f: dict) -> None:
    field_a, field_b = f["field_pair"]
    st.subheader(f"Cardinality — `{field_a}` ↔ `{field_b}`")

    expectation = f.get("expectation")
    if expectation:
        dir_desc = f"{field_a} → {field_b}" if expectation["direction"] == "A→B" else f"{field_b} → {field_a}"
        st.caption(f"Declared: {dir_desc}, expected {expectation['shape']}")

    m = f["metrics"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Shape", m["dominant_shape"])
    c2.metric("Conformance", f"{m['conf']:.1%}")
    c3.metric("Working Rows", f"{m['working_rows']:,}")
    c4.metric("Total Rows", f"{m['total_rows']:,}")
    c5.metric("Violations", m["viol_count"])

    if f.get("alarm_finding") and f.get("violations"):
        st.error(f"**{m['viol_count']} constraint violation(s) — {f['alarm_finding']}**")
        df_capped, total = _capped(f["violations"])
        st.dataframe(df_capped, use_container_width=True, hide_index=True)
        if total > ROW_CAP:
            st.caption(f"Showing {ROW_CAP} of {total} — full set in JSON export.")
    elif expectation:
        st.success("No violations — constraint satisfied.")
    else:
        st.caption("No expectation declared — informational analysis only.")

    _render_field_descriptions(f["field_descriptions"], f["llm_confidence"], f["field_descriptions_status"])
    _render_notes(f.get("notes", ""))


def _render_completeness(f: dict) -> None:
    st.subheader("Completeness Comparison")
    units = f["units"]
    st.caption(f"{len(units)} unit(s) analyzed · single-column units first, then multi-column units.")

    table_rows = []
    for r in units:
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
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    multi_results = [r for r in units if len(r["columns"]) > 1 and r["partial_rows"]]
    if multi_results:
        with st.expander("Partial row detail"):
            for r in multi_results:
                df_capped, total = _capped(r["partial_rows"])
                st.caption(f"`{r['name']}` — {total} partial row(s)")
                if not df_capped.empty:
                    st.dataframe(df_capped, use_container_width=True, hide_index=True)
                if total > ROW_CAP:
                    st.caption(f"Showing {ROW_CAP} of {total} — full set in JSON export.")

    _render_field_descriptions(f["field_descriptions"], f["llm_confidence"], f["field_descriptions_status"])
    _render_notes(f.get("notes", ""))


def _render_coverage(f: dict) -> None:
    st.subheader("Coverage Expressions")
    table_rows = [
        {"Expression": r["expression"], "Rows Satisfied": f"{r['rows_satisfied']:,}", "%": f"{r['rate']:.1%}"}
        for r in f["results"]
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    _render_field_descriptions(f["field_descriptions"], f["llm_confidence"], f["field_descriptions_status"])
    _render_notes(f.get("notes", ""))


def _render_value_distribution(f: dict) -> None:
    st.subheader(f"Value Distribution — `{f['field']}`")
    st.caption(f"{f['n_unique']} distinct value(s)")

    df_capped, total = _capped(f["distribution"])
    if not df_capped.empty:
        st.dataframe(df_capped, use_container_width=True, hide_index=True)
    if total > ROW_CAP:
        st.caption(f"Showing {ROW_CAP} of {total} — full set in JSON export.")

    _render_field_descriptions(
        {f["field"]: f["field_description"]},
        {f["field"]: f["llm_confidence"]},
        f["field_description_status"],
    )
    _render_notes(f.get("notes", ""))


RENDERERS = {
    "cardinality": _render_cardinality,
    "completeness": _render_completeness,
    "coverage": _render_coverage,
    "value_distribution": _render_value_distribution,
}

st.divider()

_remove_id = None
for i, finding in enumerate(findings):
    col_header, col_remove = st.columns([5, 1])
    with col_header:
        st.markdown(f"### Finding {i + 1}")
    with col_remove:
        if st.button("Remove", key=f"_remove_finding_{finding['finding_id']}"):
            _remove_id = finding["finding_id"]
    renderer = RENDERERS.get(finding["finding_type"])
    if renderer:
        renderer(finding)
    else:
        st.warning(f"Unknown finding type: {finding['finding_type']!r}")
    st.divider()

if _remove_id is not None:
    st.session_state["_report_findings"] = [
        f for f in st.session_state["_report_findings"] if f["finding_id"] != _remove_id
    ]
    st.rerun()
