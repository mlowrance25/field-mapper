"""Output-risk classification — a pipeline stage inserted between a
call_claude_tool result and rendering, independent of the model's own
schema guarantees (forced tool use). Flags results for analyst review;
never blocks or mutates output.

Flagged events are logged server-side (logger.warning) rather than shown
to the uploader with any detail — the person uploading a dataset may be
the one attempting the injection, and surfacing which pattern matched
would just hand them an oracle to iterate their payload against. The
caller-facing message stays generic (see pages/1_Data_Dictionary.py,
pages/2_Data_Assessment.py).

TODO(future): logger.warning is a stand-in for real reporting. This
should eventually push to the hosting organization (e.g. a webhook into
a security/ops channel) rather than relying on whoever has access to the
server's logs to notice — that integration doesn't exist yet.
"""
import re
from dataclasses import dataclass, field

from streamlit.logger import get_logger

logger = get_logger(__name__)

SUSPICIOUS_PATTERNS = [
    re.compile(r"ignore (all )?previous instructions", re.I),
    re.compile(r"system prompt", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"<\s*/?\s*(script|data)\s*>", re.I),
    re.compile(r"(disregard|forget|override|ignore)\b.{0,30}\b(instruction|prompt|rule)", re.I),
]

MAX_FIELD_NAME_LENGTH = 100
# Raised from the original ">3" — legitimate datasets are often genuinely
# homogeneous (e.g. a sensor table where every column is a "measure"), so
# this needs a wider margin before it's a meaningful signal rather than noise.
UNIFORM_CATEGORY_MIN_FIELDS = 8


@dataclass
class FlaggedField:
    field_name: str
    reasons: list = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.reasons)


def classify_output(fields: list[dict], source_profiles: list[dict]) -> dict[str, FlaggedField]:
    """Run after call_claude_tool, before rendering.

    Checks per-field content (the model's output and the source data that
    fed it) plus two batch-level signals: fields the model dropped or
    invented relative to the source profiles, and — for assessment-shaped
    results only — every field being classified into the same category,
    which is what a successful "override your instructions" injection
    would produce if it forced uniform output. Flags for analyst review;
    never blocks or mutates output.
    """
    profiles_by_name = {p["field_name"]: p for p in source_profiles}
    flags = {}

    for f in fields:
        result = FlaggedField(field_name=f["field_name"])

        for pattern in SUSPICIOUS_PATTERNS:
            if pattern.search(f.get("description", "") or ""):
                result.reasons.append(f"description matched suspicious pattern: {pattern.pattern}")
            if pattern.search(f.get("field_name", "") or ""):
                result.reasons.append(f"field_name matched suspicious pattern: {pattern.pattern}")

        if len(f.get("field_name", "") or "") > MAX_FIELD_NAME_LENGTH:
            result.reasons.append(
                f"field_name exceeds {MAX_FIELD_NAME_LENGTH} chars — possible injection payload"
            )

        profile = profiles_by_name.get(f["field_name"], {})
        for sample in profile.get("sample_values") or []:
            if not isinstance(sample, str):
                continue
            for pattern in SUSPICIOUS_PATTERNS:
                if pattern.search(sample):
                    result.reasons.append(
                        f"source sample_values matched suspicious pattern: {pattern.pattern}"
                    )
                    break

        flags[f["field_name"]] = result

    # Batch-level: fields the model dropped or invented relative to the
    # source profiles. utils.prompt_builder.reconcile_fields() already
    # surfaces this as a page-level banner in both callers — this folds
    # the same signal into the per-field flags for a single source of truth.
    input_names = {p["field_name"] for p in source_profiles}
    output_names = {f["field_name"] for f in fields}
    for invented in output_names - input_names:
        flags[invented].reasons.append("field not present in source profiles — possibly invented")
    for dropped in input_names - output_names:
        flags[dropped] = FlaggedField(
            field_name=dropped,
            reasons=["field present in source but missing from output — possibly dropped"],
        )

    # Batch-level: uniform classification. Only meaningful for
    # assessment-shaped results (field_category) — dictionary results have
    # no analogous field, so this list is empty and the check never fires there.
    categories = [f.get("field_category") for f in fields if f.get("field_category")]
    if len(categories) >= UNIFORM_CATEGORY_MIN_FIELDS and len(set(categories)) == 1:
        for result in flags.values():
            result.reasons.append("suspicious: all classified fields returned the same field_category")

    for flagged_field in flags.values():
        if flagged_field.flagged:
            logger.warning(
                "output_classifier flagged field %r: %s",
                flagged_field.field_name, "; ".join(flagged_field.reasons),
            )

    return flags