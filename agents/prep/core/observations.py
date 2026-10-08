"""Strict factual observations: no model verdict is accepted."""
from ..common import Failure, fields, number, strict_json
from .rulepacks.organizer import observation_fields


def parse(raw, criteria, images):
    try:
        value = strict_json(raw) if isinstance(raw, str) else raw
        fields(value, ("photos", "observations"))
        if not isinstance(value["photos"], list) or not isinstance(value["observations"], list):
            raise ValueError("expected arrays")
        if len(value["observations"]) > 512:
            raise ValueError("too many observations")
        authorized = {i + 1: image["ref"] for i, image in enumerate(images)}
        quality, seen, observations = {}, set(), []
        for photo in value["photos"]:
            fields(photo, ("index", "usable"))
            idx = photo["index"]
            if type(idx) is not int or idx not in authorized or idx in quality or type(photo["usable"]) is not bool:
                raise ValueError("invalid quality citation")
            quality[idx] = photo["usable"]
        allowed = observation_fields(criteria)
        for obs in value["observations"]:
            fields(obs, ("field", "value", "photo_index", "confidence", "detail"))
            name, val, idx = obs["field"], obs["value"], obs["photo_index"]
            if not isinstance(name, str) or name not in allowed or type(idx) is not int or idx not in authorized:
                raise ValueError("invalid observation citation")
            if (name, idx) in seen:
                raise ValueError("duplicate observation")
            seen.add((name, idx))
            number(obs["confidence"], 0, 1)
            if not isinstance(obs["detail"], str) or len(obs["detail"]) > 2000:
                raise ValueError("invalid detail")
            if val is not None:
                if name == "label_text":
                    if not isinstance(val, str) or not val.strip() or len(val) > 128:
                        raise ValueError("invalid transcription")
                elif name == "fnsku_placement":
                    if val not in ("flat", "seam", "curve", "edge", "unknown"):
                        raise ValueError("invalid placement")
                elif type(val) is not bool:
                    raise ValueError("presence requires boolean or null")
            observations.append({**obs, "ref": authorized[idx]})
        return {"quality": quality, "observations": observations}
    except (ValueError, TypeError, KeyError):
        raise Failure("invalid_observation") from None
