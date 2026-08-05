import json


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
# No "return ONLY JSON" instructions — output shape is enforced by the tool
# schemas below (forced tool use), so the model cannot wrap output in markdown,
# add preamble, or drop a key.

DICTIONARY_SYSTEM = """You are a data dictionary expert. You receive a profile of a dataset's
fields (name, type, null_rate, cardinality, distinct_values, min/max/mean, sample values) and,
optionally, caller-supplied context about the dataset's domain and source system.

Write a 1-2 sentence description for each field by calling the emit_data_dictionary tool. Rules:
- If dataset context is provided, use it as the primary grounding for meaning.
- If context is NOT provided, infer from field names and sample values, and lower confidence
  accordingly. Never assert domain-specific meaning you cannot support from the profile.
- Use the statistics: a ~100% null field is unpopulated/reserved; low-cardinality coded fields
  (few distinct values) should have their codes explained; single-value fields are constants or flags.
- provenance: classify each field as "pipeline" (surrogate row ids, ingest run identifiers,
  import/load timestamps, processing/review flags), "source" (originates in the underlying data),
  or "unknown" — based on field characteristics, not on any specific system.
- confidence: "high" only when grounded in provided context or unambiguous evidence; "low" when guessing.
- If a field name matches a widely recognized standard identifier, name it; otherwise describe what
  the values appear to represent. Do not restate raw statistics already in the profile."""


ASSESSMENT_SYSTEM = """You are a data analyst assessing a new dataset for the first time.
You receive a computed field profile and, optionally, caller-supplied context about the dataset's
domain and source system. Classify each field by calling the emit_assessment tool.

Rules:
- field_category: classify as identifier, classifier, measure, descriptor, flag, or date.
- is_classifier: true only for fields with a bounded set of categorical values (enums/lookups).
- classifies: list fields that this field categorizes (e.g. a status code classifies records). Usually empty.
- related_fields: list the most closely related fields by name (≤ 5). Usually 2-4 fields."""


# ---------------------------------------------------------------------------
# Tool schemas (forced tool use => guaranteed structure)
# ---------------------------------------------------------------------------

DICTIONARY_TOOL = {
    "name": "emit_data_dictionary",
    "description": "Emit one data-dictionary entry per field in the profile.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name":   {"type": "string"},
                        "description":  {"type": "string"},
                        "provenance": {
                            "type": "string",
                            "enum": ["source", "pipeline", "unknown"],
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["field_name", "description", "provenance", "confidence"],
                },
            }
        },
        "required": ["fields"],
    },
}


ASSESSMENT_TOOL = {
    "name": "emit_assessment",
    "description": "Emit one assessment entry per field in the profile.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {"type": "string"},
                        "field_category": {
                            "type": "string",
                            "enum": ["identifier", "classifier", "measure", "descriptor", "flag", "date"],
                        },
                        "is_classifier":  {"type": "boolean"},
                        "classifies":     {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                        "related_fields": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    },
                    "required": [
                        "field_name", "field_category", "is_classifier", "classifies", "related_fields",
                    ],
                },
            }
        },
        "required": ["fields"],
    },
}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_dictionary_prompt(profiles, table_name=None, dataset_context=None) -> str:
    ctx = _format_context(table_name, dataset_context)
    fp = _format_profiles(profiles)
    return (
        f"{ctx}Here is the field profile for this dataset:\n\n{fp}\n\n"
        "Generate the data dictionary by calling the emit_data_dictionary tool."
    )


def build_assessment_prompt(profiles, table_name=None, dataset_context=None) -> str:
    ctx = _format_context(table_name, dataset_context)
    fp = _format_profiles(profiles)
    return (
        f"{ctx}Here is the field profile for this dataset:\n\n{fp}\n\n"
        "Assess each field by calling the emit_assessment tool."
    )


def _format_context(table_name, dataset_context) -> str:
    parts = []
    if table_name:
        parts.append(f"- table / source name: {table_name}")
    if dataset_context and dataset_context.strip():
        parts.append(f"- description: {dataset_context.strip()}")
    if not parts:
        return ""
    return "DATASET CONTEXT (use this to ground your descriptions):\n" + "\n".join(parts) + "\n\n"


def _format_profiles(profiles) -> str:
    lines = []
    for p in profiles:
        line = (
            f"- {p['field_name']} "
            f"(type: {p['inferred_type']}, "
            f"null_rate: {p['null_rate']:.0%}, "
            f"cardinality: {p['cardinality']}"
        )
        if p.get("distinct_values") is not None:
            line += f", distinct_values: {json.dumps(p['distinct_values'])}"
        if p.get("min_value") is not None:
            line += f", min: {p['min_value']}, max: {p['max_value']}, mean: {p['mean_value']}"
        if p.get("sample_values"):
            line += f", samples: {json.dumps(p['sample_values'])}"
        line += ")"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reconciliation: catch fields the model dropped or invented
# ---------------------------------------------------------------------------

def reconcile_fields(profiles, result_fields):
    """Return (missing, extra) field names.

    missing = profiled fields the model failed to return (silent data loss).
    extra   = field names the model returned that were not in the profile (hallucination).
    """
    profiled = [p["field_name"] for p in profiles]
    profiled_set = set(profiled)
    returned = [r.get("field_name") for r in result_fields]
    returned_set = set(returned)

    missing = [f for f in profiled if f not in returned_set]
    extra = [f for f in returned if f not in profiled_set]
    return missing, extra
