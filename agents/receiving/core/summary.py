"""Maps per-check results onto the stage's contract vocabulary
(the reference receiving_sample.csv fields)."""

from typing import List

from .models import CheckResult, POLineItem

IDENTITY_KEYS = ["sku_identity", "colour", "variant"]

def build_receiving_summary(checks: List[CheckResult], po: POLineItem) -> dict:
    by = {c.check_key: c for c in checks}

    def sv(key: str) -> str:
        c = by.get(key)
        return c.summary_value if (c and c.summary_value is not None) else "uncertain"

    if any(by.get(k) and by[k].verdict == "FAIL" for k in IDENTITY_KEYS):
        identity = "no"
    elif any(by.get(k) and by[k].verdict == "UNCERTAIN" for k in IDENTITY_KEYS):
        identity = "uncertain"
    else:
        identity = "yes"

    flags = []
    if by.get("colour") and by["colour"].verdict == "FAIL":
        flags.append("wrong_colour")
    if by.get("variant") and by["variant"].verdict == "FAIL":
        flags.append("wrong_variant")
    if by.get("missing_components") and by["missing_components"].verdict == "FAIL":
        flags.append("missing_components")
    if by.get("other_quality") and by["other_quality"].verdict == "FAIL":
        flags.append("obvious_defect")

    summary = {
        "identity_match": identity,
        "carton_damage": sv("carton_damage"),
        "unit_damage": sv("unit_damage"),
        "cartons_received": sv("carton_count"),
        "units_per_carton_counted": sv("units_per_carton"),
        "qty_received": sv("quantity"),
        "quality_flags": flags,
    }

    # Authoritative formula from the reference contract:
    # qty_received = cartons_received x units_per_carton_counted.
    # Used when the direct visual count is unavailable but both factors are known.
    if summary["qty_received"] == "uncertain":
        try:
            c = int(summary["cartons_received"])
            u = int(summary["units_per_carton_counted"])
            summary["qty_received"] = str(c * u)
            summary["qty_received_source"] = "derived (cartons x units_per_carton)"
        except (TypeError, ValueError):
            pass
    return summary