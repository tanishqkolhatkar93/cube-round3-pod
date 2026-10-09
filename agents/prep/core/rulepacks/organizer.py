"""Attributed port of upstream prepRequirements.ts / rulePacks/fba-v1.ts.

These are organizer-supplied implementation rules, NOT independently verified
marketplace policy. Applicability comes from explicit versioned operator criteria.
"""
import re
from ...common import fields, text

SOURCE_COMMIT = "f5f8ad98fa8085a092c796b0681689d52ffc871e"
RULE_VERSION = "organizer-fba@1-pod14.1"
SOURCE_URL = "https://github.com/Manvith111/cube26-prp-0319-manvith111"
# (canonical check key, observation field, expected factual value, clause)
CHECKS = (
    ("polybag_present", "polybag_present", True, "2.1"),
    ("polybag_sealed", "polybag_sealed", True, "2.2"),
    ("suffocation_warning_present", "suffocation_warning_present", True, "2.3"),
    ("suffocation_warning_legible", "suffocation_warning_legible", True, "2.3"),
    ("fnsku_present", "fnsku_present", True, "3.1"),
    ("fnsku_label_placement", "fnsku_placement", "flat", "3.2"),
    ("fnsku_text_match", "label_text", None, "3.3"),
    ("original_barcode_covered", "original_barcode_covered", True, "3.4"),
    ("expiry_legible", "expiry_visible", True, "4.1"),
)


def validate_criteria(value):
    fields(value, ("criteria_id", "version", "source", "rule_pack", "sku", "expected_fnsku",
                   "requires_polybag", "requires_suffocation_warning", "cover_original_barcode",
                   "has_expiry", "required_handling_marks"))
    for key in ("criteria_id", "version", "source", "sku"):
        text(value[key])
    if value["rule_pack"] != RULE_VERSION:
        raise ValueError("unknown rule pack")
    if not isinstance(value["expected_fnsku"], str) or not re.fullmatch(r"[A-Z0-9]{1,64}", value["expected_fnsku"]):
        raise ValueError("expected FNSKU must be exact uppercase alphanumeric")
    for key in ("requires_polybag", "requires_suffocation_warning", "cover_original_barcode", "has_expiry"):
        if type(value[key]) is not bool:
            raise ValueError("explicit boolean applicability required")
    marks = value["required_handling_marks"]
    if not isinstance(marks, list) or len(marks) > 32:
        raise ValueError("invalid marks")
    for mark in marks:
        text(mark)
    if len(set(marks)) != len(marks):
        raise ValueError("duplicate handling mark")
    return value


def applicable(field, criteria):
    if field.startswith("polybag_"):
        return criteria["requires_polybag"]
    if field.startswith("suffocation_"):
        return criteria["requires_suffocation_warning"]
    if field == "original_barcode_covered":
        return criteria["cover_original_barcode"]
    if field == "expiry_visible":
        return criteria["has_expiry"]
    return True


def observation_fields(criteria):
    return {item[1] for item in CHECKS} | {"handling_mark:" + mark for mark in criteria["required_handling_marks"]}
