import os
from pathlib import Path
from agents.gemini_credentials import configured_api_key

AGENT_DIR = Path(__file__).resolve().parents[1]     # agents/receiving
REPO_ROOT = Path(__file__).resolve().parents[3]     # pod repo root

class Config:
    provider: str = os.environ.get('RECEIVING_PROVIDER', 'gemini')
    if provider not in ('gemini', 'groq'):
        raise ValueError('invalid_receiving_provider')
    gemini_api_key: str = configured_api_key() if provider == 'gemini' else ''
    groq_model: str = os.environ.get('RECEIVING_GROQ_MODEL', 'qwen/qwen3.8-27b')
    groq_api_key_env: str = os.environ.get('GROQ_API_KEY_ENV', 'GROQ_API_KEY')
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    gemini_fallback_models: list = [m.strip() for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
    cache_dir: Path = Path(os.environ.get("RECEIVING_CACHE_DIR", REPO_ROOT / "out" / "receiving-cache"))
    timeout_s: float = float(os.environ.get("RECEIVING_TIMEOUT_S", "20"))
    prompts_dir: Path = AGENT_DIR / "prompts"

CFG = Config()


def provider_selection():
    if CFG.provider == 'groq':
        return {'kind': 'groq', 'model': CFG.groq_model, 'api_key_env': CFG.groq_api_key_env,
                'deadline_s': CFG.timeout_s}
    return {'kind': 'gemini', 'model': CFG.gemini_model, 'fallbacks': CFG.gemini_fallback_models}

# Input capture root: refs resolve ONLY inside this directory (see app._safe_rel)
DATA_INPUT = Path(os.environ.get("INPUT_DIR", str(REPO_ROOT / "data" / "input")))
