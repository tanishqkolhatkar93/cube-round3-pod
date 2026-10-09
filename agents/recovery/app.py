"""Recovery input and evidence boundary shared by direct and HTTP execution."""
from agents.secure_runtime import make_app
from .adapter import handle

app = make_app("recovery", handle)
