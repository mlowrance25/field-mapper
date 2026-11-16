import importlib.metadata
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


def init_report_findings() -> None:
    if "_report_findings" not in st.session_state:
        st.session_state["_report_findings"] = []


def new_finding_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def field_enrichment(field_names: list[str]) -> dict:
    """Look up field descriptions + LLM confidence for the given fields from
    the V1 Data Dictionary output (st.session_state["dictionary_result"]),
    if it exists.

    Absence is always explicit, never a silently omitted key: `status` is
    "not_run" only when Data Dictionary generation itself was never run;
    "available" when every requested field has a dictionary entry;
    "partial" otherwise (Dictionary was run, but doesn't cover every field
    this finding references).

    `llm_confidence` is the LLM's own self-reported confidence in its
    description (high/medium/low) — NOT a human-confirmation signal. No
    such signal exists anywhere in Data Dictionary today; don't conflate
    the two when rendering.
    """
    dictionary_result = st.session_state.get("dictionary_result")
    if not dictionary_result:
        return {
            "field_descriptions": {name: None for name in field_names},
            "llm_confidence": {name: None for name in field_names},
            "status": "not_run",
        }

    dict_map = {r["field_name"]: r for r in dictionary_result}
    field_descriptions = {}
    llm_confidence = {}
    found_count = 0
    for name in field_names:
        entry = dict_map.get(name)
        field_descriptions[name] = entry.get("description") if entry else None
        llm_confidence[name] = entry.get("confidence") if entry else None
        if entry:
            found_count += 1

    status = "available" if found_count == len(field_names) else "partial"

    return {
        "field_descriptions": field_descriptions,
        "llm_confidence": llm_confidence,
        "status": status,
    }


def single_field_enrichment(field_name: str) -> dict:
    """Convenience wrapper for value_distribution's single-field case.

    Uses the same three-state status (not_run/partial/available) as the
    multi-field case for consistency — a single field that isn't in a
    Dictionary that WAS run is "partial", not silently collapsed into
    "not_run", so that distinction (never run vs. run but doesn't cover
    this field) isn't lost.
    """
    result = field_enrichment([field_name])
    return {
        "field_description": result["field_descriptions"][field_name],
        "llm_confidence": result["llm_confidence"][field_name],
        "field_description_status": result["status"],
    }


def export_metadata() -> dict:
    """Provenance metadata attached to every report export (CSV + JSON) —
    lets a shared export be traced back to what produced it without any
    server-side persistence.
    """
    try:
        tool_version = importlib.metadata.version("field-mapper")
    except importlib.metadata.PackageNotFoundError:
        tool_version = _read_version_from_pyproject()

    return {
        "dataset": st.session_state.get("filename", "unknown"),
        "generated_at": now_iso(),
        "tool_version": tool_version,
    }


def _read_version_from_pyproject() -> str:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except Exception:
        return "unknown"
