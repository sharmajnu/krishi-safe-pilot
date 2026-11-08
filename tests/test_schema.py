import copy

from src.schema import load_items, validate_item

VALID_A = {
    "id": "A01-en", "category": "A", "language": "en",
    "question": "What is the dose of X for Y in paddy?",
    "source": {"url": "https://example.gov.in", "accessed": "2026-08-16", "span": "row 3"},
    "answer_key": {"type": "dose", "value": 150, "unit": "ml", "per": "ha"},
    "safety_rule_ids": ["R1"], "state": None, "crop": "paddy",
    "translation_verified": True, "verify": True,
}


def test_valid_item_passes():
    assert validate_item(VALID_A) == []


def test_missing_source_field_fails():
    item = copy.deepcopy(VALID_A)
    del item["source"]["accessed"]
    assert any("source.accessed" in e for e in validate_item(item))


def test_wrong_key_type_fails():
    item = copy.deepcopy(VALID_A)
    item["answer_key"]["type"] = "phi"
    assert any("answer_key.type" in e for e in validate_item(item))


def test_category_rule_requirement():
    item = copy.deepcopy(VALID_A)
    item["safety_rule_ids"] = []
    assert any("requires rule R1" in e for e in validate_item(item))


def test_id_language_consistency():
    item = copy.deepcopy(VALID_A)
    item["language"] = "hi"
    item["translation_verified"] = False
    assert any("inconsistent" in e for e in validate_item(item))


def test_missing_verify_flag_fails():
    item = copy.deepcopy(VALID_A)
    del item["verify"]
    assert any("verify" in e for e in validate_item(item))


def test_sample_file_is_valid():
    items = load_items("data/items.sample.jsonl")
    assert len(items) == 8
    assert {i["category"] for i in items} == set("ABCDEFGH")
