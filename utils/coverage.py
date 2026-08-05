import re

from utils.completeness import _presence_mask

_AND = "AND"
_OR = "OR"


def _validate_grouping(expr: str) -> None:
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
            if depth > 1:
                raise ValueError(f"nested grouping not supported (max one level): {expr!r}")
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced parentheses: {expr!r}")
    if depth != 0:
        raise ValueError(f"unbalanced parentheses: {expr!r}")


def _reject_not(expr: str) -> None:
    if re.search(r"(?i)\bnot\b", expr):
        raise ValueError(f"NOT is not supported in coverage expressions: {expr!r}")


def validate_expression(expr: str, units: dict[str, list[str]]) -> None:
    """Raise ValueError if `expr` violates the grammar or references an
    undeclared unit. Does not evaluate — for inline UI validation as the
    analyst types, before a dataset pass is worth running.
    """
    _validate_grouping(expr)
    _reject_not(expr)
    _tokenize(expr, units)


def _tokenize(expr: str, units: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    working = expr
    placeholder_map: dict[str, str] = {}
    for i, name in enumerate(sorted(units.keys(), key=len, reverse=True)):
        placeholder = f"__UNIT_{i}__"
        pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
        working, n = pattern.subn(placeholder, working)
        if n:
            placeholder_map[placeholder] = name

    working = working.replace("(", " ( ").replace(")", " ) ")
    tokens = []
    for t in working.split():
        tu = t.upper()
        if t in ("(", ")"):
            tokens.append(t)
        elif tu in (_AND, _OR):
            tokens.append(tu)
        elif t in placeholder_map:
            tokens.append(t)
        else:
            raise ValueError(
                f"unknown term {t!r} in expression: {expr!r} — declare it as a unit first"
            )
    return tokens, placeholder_map


def _parse_or(tokens, pos, presence_masks, placeholder_map):
    mask, pos = _parse_and(tokens, pos, presence_masks, placeholder_map)
    while pos < len(tokens) and tokens[pos] == _OR:
        rhs, pos = _parse_and(tokens, pos + 1, presence_masks, placeholder_map)
        mask = mask | rhs
    return mask, pos


def _parse_and(tokens, pos, presence_masks, placeholder_map):
    mask, pos = _parse_atom(tokens, pos, presence_masks, placeholder_map)
    while pos < len(tokens) and tokens[pos] == _AND:
        rhs, pos = _parse_atom(tokens, pos + 1, presence_masks, placeholder_map)
        mask = mask & rhs
    return mask, pos


def _parse_atom(tokens, pos, presence_masks, placeholder_map):
    if pos >= len(tokens):
        raise ValueError("unexpected end of expression")
    tok = tokens[pos]
    if tok == "(":
        mask, pos = _parse_or(tokens, pos + 1, presence_masks, placeholder_map)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise ValueError("expected closing parenthesis")
        return mask, pos + 1
    if tok in placeholder_map:
        return presence_masks[placeholder_map[tok]], pos + 1
    raise ValueError(f"unexpected token: {tok!r}")


def evaluate_coverage(df, units: dict[str, list[str]], expressions: list[str]) -> list[dict]:
    """Evaluate boolean AND/OR coverage expressions over units already declared
    in the completeness comparison.

    Grammar is intentionally minimal (PRD-002 contract, not implementer
    discretion): unit-name terms, AND, OR, one level of parenthetical
    grouping. No NOT, no nested grouping. Expressions are cumulative — a row
    can satisfy more than one expression — this is not a mutually-exclusive
    partition.
    """
    if not units:
        raise ValueError("no units available — declare units in the completeness comparison first")
    if not expressions:
        raise ValueError("at least one expression must be declared")

    total_rows = len(df)
    presence_masks = {}
    for name, cols in units.items():
        missing_cols = [c for c in cols if c not in df.columns]
        if missing_cols:
            raise ValueError(f"columns not in dataset: {missing_cols}")
        presence_masks[name] = _presence_mask(df, cols).all(axis=1)

    results = []
    for expr in expressions:
        _validate_grouping(expr)
        _reject_not(expr)
        tokens, placeholder_map = _tokenize(expr, units)
        mask, pos = _parse_or(tokens, 0, presence_masks, placeholder_map)
        if pos != len(tokens):
            raise ValueError(f"unexpected trailing tokens in expression: {expr!r}")
        rows_satisfied = int(mask.sum())
        results.append({
            "expression": expr,
            "rows_satisfied": rows_satisfied,
            "rate": rows_satisfied / total_rows if total_rows else 0.0,
        })
    return results