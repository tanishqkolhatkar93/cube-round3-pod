"""Explicit process-level Gemini credential selection; never rotation or failover."""
import os


def configured_api_key():
    name = os.environ.get("GEMINI_API_KEY_ENV", "GEMINI_API_KEY")
    if name not in {"GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"}:
        raise ValueError("invalid_gemini_key_selector")
    # Missing selected credentials stay missing, even if another key is available.
    return os.environ.get(name, "")
