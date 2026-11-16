# Output classification — feasibility of integration

Two concrete insertion points, one naming collision to flag.

## Data_Dictionary page (`pages/1_Data_Dictionary.py:174-191`)

This is the finalize branch of the batch pipeline (`_dict_pending` loop reruns
once per batch, then falls through here once `idx >= len(batches)`). Insert
right after `fields = st.session_state.pop("_dict_results")` (line 175),
using the `profiles` local var still in scope (line 161) as `source_profiles`,
and cache the result:

```python
flags = classify_output(fields, profiles)
st.session_state["dictionary_flags"] = flags
```

Rendering is a per-row loop already (line 235-241), so showing it is just
`flag = flags[row["field_name"]]` next to the existing
`st.markdown(f"**{row.get('field_name','')}**")` — the wiring snippet
written earlier is accurate for this page as-is.

Important: compute it once at finalization, not inside the render loop —
Streamlit reruns the whole script on every widget interaction, so if
`classify_output` lived in the render loop it'd redundantly recompute every
time you touch an unrelated widget on the page.

## Data_Assessment page

Same finalize pattern exists (pop `_assess_results`, build `assessment_result`
+ `assessment_profiles`), so the insertion point mirrors the dictionary page.
But rendering is different: it's a bulk `st.dataframe(display_df, ...)`
(line 195), not a per-row loop, and `display_df` already has a `"flags"`
column (line 150: `make_flags(r, profile, dict_entry)`) driving a
flagged/pipeline count summary (lines 159-160). That column is existing
data-quality signal — reusing the name for injection-risk flags would
conflate two different things in one UI cell. It needs its own column
(e.g. `"risk_flags"`) added to `display_df` alongside the `make_flags`
call, with its own `column_config` entry.

## MCP server

Doesn't need this at all right now — `mcp_server.py`'s two tools
(`analyze_completeness_tool`, `evaluate_coverage_tool`) are deterministic,
no LLM call in that path. Scope is genuinely just the two Streamlit pages
above today, which is worth saying plainly — it's a smaller lift than
"everywhere the model is called" sounds like.

---

# Response to other agent's review of utils/output_classifier.py

Vetting each claim before implementing — one has a bug that would ship
dead code, two are worth pushing back on for false-positive risk.

**#2 — reconciliation part is a duplicate, not a gap.** `reconcile_fields()`
already exists in `prompt_builder.py` and both pages already call it,
rendering `st.error`/`st.warning` banners for dropped/invented fields
(`pages/1_Data_Dictionary.py:181-185`, `pages/2_Data_Assessment.py:57-61`).
The real ask here is *consolidating* that signal into the `flags` dict so
it shows up in one place instead of a separate banner — legitimate idea,
just not a new detection.

**#2 — uniform-category check has a bug as pasted.** `f.get("category")`
doesn't exist in either tool schema — `DICTIONARY_TOOL` fields are
`field_name/description/provenance/confidence`, `ASSESSMENT_TOOL` fields
are `field_name/field_category/is_classifier/classifies/related_fields`.
As written, `categories` is always empty and the check never fires —
silent dead code. It'd need to be `field_category`, and it only makes
sense for the assessment path — the dictionary path has nothing
analogous. Also worth flagging: "same category across >3 fields" will
false-positive on plenty of legitimate datasets (a sensor table where
every column is genuinely a `measure`, a survey where most fields are
`flag`s). Raise the bar or drop it rather than ship a noisy signal —
same failure mode already ruled out for the hard-gate pre-scan earlier
in this thread.

**#3 — the compound pattern is good, the three bare-word patterns
aren't.** `(disregard|forget|override|ignore)\b.{0,30}\b(instruction|
prompt|rule)` is a reasonable, appropriately-scoped expansion — keep it.
But `\bact as\b`, `\bdisregard\b`, and `\boverride\b` as standalone
matches are too broad for this domain specifically: this is a
data-dictionary tool, and `override` shows up constantly in legitimate
field content (`override_flag`, `override_reason`, "indicates an
override was applied"). Flagging every bare occurrence produces exactly
the alert-fatigue problem flagged earlier for the pre-scan gate. They're
also redundant with the compound pattern, which already captures the
actually-suspicious combination — drop the three bare-word ones.

**#4 — field_name length check is solid, apply as-is.** Column headers
over 100 chars essentially never occur naturally, so false-positive risk
is near zero. If also applied to `description`, it needs a much higher
threshold — the system prompt asks for 1-2 sentences, so 100 chars is
normal there, not anomalous.

Proposed scope to implement: reconciliation folded into `flags`,
corrected `field_category` uniformity check (assessment-only, bar
raised), the compound regex only (not the three bare-word patterns), and
the `field_name` length check.