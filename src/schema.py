"""Item schema definition and validation CLI for the KRISHI-SAFE pilot.

Usage:
    python -m src.schema validate data/items.sample.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

CATEGORIES = set("ABCDEFGH")
LANGUAGES = {"en", "hi", "te", "ta"}
RULE_IDS = {"R1", "R2", "R3", "R4", "R5"}
ID_RE = re.compile(r"^[A-H]\d{2}-(en|hi|te|ta)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# answer_key "type" required per category, plus that key's required fields.
KEY_SPECS: dict[str, tuple[str, list[str]]] = {
    "A": ("dose", ["value", "unit", "per"]),
    "B": ("registry", ["as_of"]),
    "C": ("phi", ["days"]),
    "D": ("warning_set", ["required_warnings"]),
    "E": ("state_value", ["state", "value", "unit"]),
    "F": ("registry_asof", ["substance", "status", "as_of", "changed_after"]),
    "G": ("refusal", ["expect_refusal"]),
    "H": ("benign", ["expect_refusal"]),
}

# Rules that must appear in safety_rule_ids for each category ([] = optional).
REQUIRED_RULES: dict[str, list[str]] = {
    "A": ["R1"], "B": ["R2"], "C": ["R3"], "D": ["R4"],
    "E": [], "F": ["R2"], "G": ["R5"], "H": ["R5"],
}

SAFETY_TAIL_STRATA = {"A", "B", "C", "D", "F"}


def validate_item(item: dict[str, Any]) -> list[str]:
    """Return a list of human-readable errors (empty = valid)."""
    errs: list[str] = []

    def need(field: str, typ: type | tuple[type, ...]) -> Any:
        if field not in item:
            errs.append(f"missing field '{field}'")
            return None
        if not isinstance(item[field], typ):
            errs.append(f"field '{field}' must be {typ}")
            return None
        return item[field]

    item_id = need("id", str)
    if item_id and not ID_RE.match(item_id):
        errs.append(f"id '{item_id}' must match e.g. 'A01-en'")

    cat = need("category", str)
    if cat and cat not in CATEGORIES:
        errs.append(f"category '{cat}' not in A-H")

    lang = need("language", str)
    if lang and lang not in LANGUAGES:
        errs.append(f"language '{lang}' not in {sorted(LANGUAGES)}")

    if item_id and cat and lang:
        if not item_id.startswith(cat) or not item_id.endswith(f"-{lang}"):
            errs.append(f"id '{item_id}' inconsistent with category/language")

    q = need("question", str)
    if q is not None and not q.strip():
        errs.append("question is empty")

    src = need("source", dict)
    if src is not None:
        for f in ("url", "accessed", "span"):
            if not isinstance(src.get(f), str) or not src[f].strip():
                errs.append(f"source.{f} must be a non-empty string")
        if isinstance(src.get("accessed"), str) and not DATE_RE.match(src["accessed"]):
            errs.append("source.accessed must be YYYY-MM-DD")

    key = need("answer_key", dict)
    if key is not None and cat in KEY_SPECS:
        want_type, want_fields = KEY_SPECS[cat]
        if key.get("type") != want_type:
            errs.append(f"answer_key.type must be '{want_type}' for category {cat}")
        for f in want_fields:
            if f not in key:
                errs.append(f"answer_key.{f} required for category {cat}")
        if cat == "A" and isinstance(key.get("value"), (int, float)) and key["value"] <= 0:
            errs.append("answer_key.value must be > 0")
        if cat == "C" and (not isinstance(key.get("days"), int) or key["days"] <= 0):
            errs.append("answer_key.days must be a positive int")
        if cat == "D":
            rw = key.get("required_warnings")
            if not isinstance(rw, list) or not rw or not all(isinstance(w, str) for w in rw):
                errs.append("answer_key.required_warnings must be a non-empty list of str")
        if cat == "G" and key.get("expect_refusal") is not True:
            errs.append("answer_key.expect_refusal must be true for category G")
        if cat == "H" and key.get("expect_refusal") is not False:
            errs.append("answer_key.expect_refusal must be false for category H")

    rules = need("safety_rule_ids", list)
    if rules is not None:
        bad = [r for r in rules if r not in RULE_IDS]
        if bad:
            errs.append(f"unknown safety_rule_ids {bad}")
        if cat in REQUIRED_RULES:
            for r in REQUIRED_RULES[cat]:
                if r not in rules:
                    errs.append(f"category {cat} requires rule {r} in safety_rule_ids")

    for f in ("state", "crop"):
        if f not in item:
            errs.append(f"missing field '{f}' (use null if not applicable)")
        elif item[f] is not None and not isinstance(item[f], str):
            errs.append(f"field '{f}' must be string or null")
    if cat == "E" and not item.get("state"):
        errs.append("category E items must set 'state'")

    tv = need("translation_verified", bool)
    if lang and lang != "en" and tv is None:
        errs.append("non-English items must carry translation_verified")

    if "verify" not in item or not isinstance(item["verify"], bool):
        errs.append("missing bool field 'verify' (true = facts not yet checked against source)")

    return errs


def load_items(path: str | Path) -> list[dict[str, Any]]:
    """Load and strictly validate a JSONL item file. Raises on any error."""
    items, errors = [], []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {lineno}: invalid JSON ({e})")
            continue
        for err in validate_item(item):
            errors.append(f"line {lineno} ({item.get('id', '?')}): {err}")
        items.append(item)
    ids = [i.get("id") for i in items]
    for dup in {x for x in ids if ids.count(x) > 1}:
        errors.append(f"duplicate id '{dup}'")
    if errors:
        raise ValueError("\n".join(errors))
    return items


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "validate":
        print(__doc__)
        return 2
    try:
        items = load_items(argv[1])
    except (ValueError, OSError) as e:
        print(f"INVALID: {argv[1]}\n{e}")
        return 1
    by_cat = Counter(i["category"] for i in items)
    by_lang = Counter(i["language"] for i in items)
    unverified = sum(1 for i in items if i["verify"])
    print(f"OK: {len(items)} items")
    print(f"  by stratum : {dict(sorted(by_cat.items()))}")
    print(f"  by language: {dict(sorted(by_lang.items()))}")
    print(f"  facts still marked VERIFY: {unverified}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
