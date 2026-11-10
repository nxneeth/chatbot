"""Central configuration, read from environment variables (and backend/.env)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    # --- Database -------------------------------------------------------
    # Use "memory" to run fully offline from backend/data/legacy (demo mode).
    MONGO_URI = _env("MONGO_URI", "memory")
    MONGO_DB = _env("MONGO_DB", "edulayne")

    # --- Auth -----------------------------------------------------------
    JWT_SECRET = _env("JWT_SECRET", "change-me-in-.env")
    JWT_EXPIRE_MINUTES = int(_env("JWT_EXPIRE_MINUTES", "480"))

    # --- LLM (any OpenAI-compatible endpoint: Groq, Ollama, OpenRouter...) -
    LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    LLM_API_KEY = _env("LLM_API_KEY") or _env("GROQ_API_KEY")
    LLM_MODEL = _env("LLM_MODEL", "openai/gpt-oss-120b")
    LLM_ROUTER_MODEL = _env("LLM_ROUTER_MODEL", "openai/gpt-oss-20b")
    # "low" / "medium" / "high" for reasoning models on Groq; leave empty for Ollama/Llama.
    LLM_REASONING_EFFORT = _env("LLM_REASONING_EFFORT", "low")
    LLM_TIMEOUT = float(_env("LLM_TIMEOUT", "30"))

    # --- Academic thresholds -------------------------------------------
    LOW_ATTENDANCE = float(_env("LOW_ATTENDANCE", "75"))
    DEFAULT_PASS_MARK = float(_env("DEFAULT_PASS_MARK", "40"))

    # --- Misc ------------------------------------------------------------
    CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    RULES_DIR = Path(_env("RULES_DIR", str(BASE_DIR / "rules")))
    LEGACY_DATA_DIR = Path(_env("LEGACY_DATA_DIR", str(BASE_DIR / "data" / "legacy")))
    SEED_USERS_FILE = Path(_env("SEED_USERS_FILE", str(BASE_DIR / "seed_users.json")))

    @property
    def llm_enabled(self) -> bool:
        # Ollama needs no key; hosted providers do.
        return bool(self.LLM_API_KEY) or "localhost" in self.LLM_BASE_URL or "127.0.0.1" in self.LLM_BASE_URL


settings = Settings()
