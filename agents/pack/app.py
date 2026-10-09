"""Actual Pack entry point used by both orchestration and HTTP."""
from agents.secure_runtime import make_app
from .adapter import handle

app = make_app("pack", handle)
