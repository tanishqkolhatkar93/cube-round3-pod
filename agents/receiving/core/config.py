import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]     # agents/receiving
REPO_ROOT = Path(__file__).resolve().parents[3]     # pod repo root

def _load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

class Config:
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    gemini_fallback_models: list = [m.strip() for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
    cache_dir: Path = REPO_ROOT / ".cache" / "extraction"
    prompts_dir: Path = AGENT_DIR / "prompts"

CFG = Config()