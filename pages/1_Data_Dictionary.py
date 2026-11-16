import json
import pandas as pd
import streamlit as st

from utils.profiler import profile_dataframe
from utils.claude_client import call_claude_tool
from utils.output_classifier import classify_output

DICT_BATCH_SIZE = 8
from utils.prompt_builder import (
    DICTIONARY_SYSTEM,
    DICTIONARY_TOOL,
    build_dictionary_prompt,
    reconcile_fields,
)

import time
import os
import anthropic
from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="Data Dictionary — FieldMapper", layout="wide")
st.title("Data Dictionary")

with st.expander("🔧 API diagnostics"):
    col_a, col_b = st.columns(2)

    with col_a:
        if st.button("Test basic API"):
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            st.write(f"Key: `{'yes — ' + api_key[:8] + '...' if api_key else 'NO'}`")
            try:
                client = anthropic.Anthropic(api_key=api_key)
                t0 = time.time()
                r = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Reply: ok"}],
                    timeout=30.0,
                )
                st.success(f"OK in {time.time()-t0:.1f}s: {r.content[0].text!r}")
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")

    with col_b:
        if st.button("Test tool use (3 fields, Haiku)"):
            try:
                from utils.prompt_builder import DICTIONARY_SYSTEM, DICTIONARY_TOOL, build_dictionary_prompt
                from utils.profiler import profile_dataframe
                import pandas as pd
                mini_df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "status": ["active", "inactive"]})
                profiles = profile_dataframe(mini_df)
                prompt = build_dictionary_prompt(profiles, table_name="test")
                client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
                t0 = time.time()
                with client.messages.stream(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=DICTIONARY_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                    tools=[DICTIONARY_TOOL],
                    tool_choice={"type": "tool", "name": "emit_data_dictionary"},
                ) as stream:
                    for _ in stream:
                        pass
                    resp = stream.get_final_message()
                    print(resp)
                fields = next((b.input.get("fields", []) for b in resp.content if b.type == "tool_use"), [])
                st.success(f"OK in {time.time()-t0:.1f}s — {len(fields)} fields returned")
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")

    col_c, col_d = st.columns(2)
    with col_c:
        if st.button("Test Ollama (ping)"):
            import urllib.request
            payload = json.dumps({
                "model": "qwen3:1.7b",
                "prompt": "Reply with just the word: ok",
                "stream": False,
            }).encode()
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    "http://localhost:11434/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read())
                st.success(f"Ollama OK in {time.time()-t0:.1f}s: {result.get('response', '')!r}")
            except Exception as e:
                st.error(f"Ollama {type(e).__name__}: {e}")

    with col_d:
        if st.button("Generate Dictionary (Ollama)"):
            if "df" in st.session_state:
                import urllib.request as _ureq
                from utils.profiler import profile_dataframe as _profile
                from utils.prompt_builder import build_dictionary_prompt as _build_prompt, reconcile_fields as _reconcile

                _df = st.session_state["df"]
                _filename = st.session_state["filename"]
                _stem = _filename.rsplit(".", 1)[0]
                _ctx = st.session_state.get("dataset_context", "")
                _profiles = _profile(_df)
                _user_prompt = _build_prompt(_profiles, table_name=_stem, dataset_context=_ctx)

                _system = (
                    "You are a data dictionary expert. For each field listed, write a 1-2 sentence description. "
                    "Classify provenance as source, pipeline, or unknown. "
                    "Classify confidence as high, medium, or low. "
                    "Return ONLY valid JSON matching exactly: "
                    '{\"fields\": [{\"field_name\": \"...\", \"description\": \"...\", \"provenance\": \"...\", \"confidence\": \"...\"}]}'
                    " No markdown, no explanation, no <think> tags — JSON only."
                )
                _payload = json.dumps({
                    "model": "qwen3:1.7b",
                    "prompt": f"{_system}\n\n{_user_prompt}",
                    "stream": False,
                    "format": "json",
                }).encode()

                t0 = time.time()
                with st.spinner("Running via Ollama qwen3:1.7b…"):
                    try:
                        _req = _ureq.Request(
                            "http://localhost:11434/api/generate",
                            data=_payload,
                            headers={"Content-Type": "application/json"},
                        )
                        with _ureq.urlopen(_req, timeout=300) as _resp:
                            _result = json.loads(_resp.read())
                        elapsed = time.time() - t0
                        _raw = _result.get("response", "{}")
                        print(_result)
                        print("Raw result")
                        print(_raw)
                        _parsed = json.loads(_raw)
                        _fields = _parsed.get("fields", [])
                        st.success(f"Ollama done in {elapsed:.1f}s — {len(_fields)} fields")
                        st.session_state["dictionary_result"] = _fields
                    except Exception as e:
                        st.error(f"Ollama error: {type(e).__name__}: {e}")
            else:
                st.warning("Upload a dataset first.")

if "df" not in st.session_state:
    st.warning("No dataset loaded. Go to the **Upload** page first.")
    st.stop()

df = st.session_state["df"]
filename = st.session_state["filename"]
stem = filename.rsplit(".", 1)[0]
dataset_context = st.session_state.get("dataset_context", "")

st.caption(f"Dataset: **{filename}** — {len(df):,} rows × {len(df.columns)} columns")

# --- one-batch-per-rerun pipeline -------------------------------------------
if st.session_state.get("_dict_pending"):
    profiles = st.session_state["_dict_profiles"]
    idx = st.session_state["_dict_idx"]
    batches = [profiles[i:i + DICT_BATCH_SIZE] for i in range(0, len(profiles), DICT_BATCH_SIZE)]

    if idx < len(batches):
        batch = batches[idx]
        with st.spinner(f"Generating dictionary… batch {idx+1}/{len(batches)}"):
            prompt = build_dictionary_prompt(batch, table_name=stem, dataset_context=dataset_context)
            print(f"[dict] batch {idx+1}/{len(batches)} — {len(prompt)} chars")
            result = call_claude_tool(DICTIONARY_SYSTEM, prompt, DICTIONARY_TOOL, "emit_data_dictionary")
            st.session_state["_dict_results"].extend(result.get("fields", []))
            st.session_state["_dict_idx"] += 1
        st.rerun()
    else:
        fields = st.session_state.pop("_dict_results")
        st.session_state.pop("_dict_pending", None)
        st.session_state.pop("_dict_idx", None)
        type_by_field = {p["field_name"]: p["inferred_type"] for p in profiles}
        st.session_state.pop("_dict_profiles", None)

        missing, extra = reconcile_fields(profiles, fields)
        if missing:
            st.error(f"Claude did not return {len(missing)} field(s): {', '.join(missing)}. Re-run.")
        if extra:
            st.warning(f"Claude returned field(s) not in the dataset: {', '.join(extra)}.")

        for row in fields:
            row["inferred_type"] = type_by_field.get(row.get("field_name"), "")

        st.session_state["dictionary_flags"] = classify_output(fields, profiles)
        st.session_state["dictionary_result"] = fields
        st.rerun()

if st.button("Generate Dictionary", type="primary"):
    profiles = profile_dataframe(df)
    print(f"[dict] profiler done — {len(profiles)} fields")
    st.session_state["_dict_pending"] = True
    st.session_state["_dict_idx"] = 0
    st.session_state["_dict_results"] = []
    st.session_state["_dict_profiles"] = profiles
    st.rerun()

if "dictionary_result" in st.session_state:
    result = st.session_state["dictionary_result"]
    result_flags = st.session_state.get("dictionary_flags", {})
    result_df = pd.DataFrame(result)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download CSV",
            data=result_df.to_csv(index=False),
            file_name=f"{stem}_dictionary.csv",
            mime="text/csv",
        )
    with col2:
        st.download_button(
            "Download JSON",
            data=json.dumps(result, indent=2),
            file_name=f"{stem}_dictionary.json",
            mime="application/json",
        )

    st.divider()

    PROVENANCE_BADGE = {
        "source":   "🟢 source",
        "pipeline": "⚙️ pipeline",
        "unknown":  "❓ unknown",
    }
    CONFIDENCE_BADGE = {
        "high":   "",
        "medium": " · ⚠️ medium confidence",
        "low":    " · ⚠️ low confidence",
    }

    for row in result:
        flag = result_flags.get(row.get("field_name", ""))
        col_name, col_type = st.columns([3, 1])
        with col_name:
            if flag and flag.flagged:
                # Deliberately generic — the uploader may be the source of
                # the issue, so specifics stay server-side (see
                # utils/output_classifier.py logger.warning).
                st.markdown(
                    f"**{row.get('field_name', '')}** ⚠️",
                    help="Automated analysis has limited confidence in this field and it has been flagged for review.",
                )
            else:
                st.markdown(f"**{row.get('field_name', '')}**")
        with col_type:
            st.caption(row.get("inferred_type", ""))
        st.write(row.get("description", ""))
        prov = PROVENANCE_BADGE.get(row.get("provenance"), row.get("provenance", ""))
        conf = CONFIDENCE_BADGE.get(row.get("confidence"), "")
        st.caption(f"{prov}{conf}")
        st.divider()

    st.caption("AI-generated output. Human review recommended before use in production.")
