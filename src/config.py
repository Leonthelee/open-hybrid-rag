import os
import logging
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
)
logger = logging.getLogger("open_hybrid_rag")

class PrivacyMode(str, Enum):
    LOCAL_ONLY = "local_only"
    HYBRID = "hybrid"

# Server Settings (Localhost by default for secure isolation)
HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", 8000))

# Security & API Authentication
API_KEY = os.getenv("API_KEY", "").strip()
if API_KEY in ("your_api_key_here", "your-api-key", "change_me_in_production"):
    API_KEY = ""

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").strip()

# Privacy Guard Strict Validation
_raw_privacy = os.getenv("PRIVACY_MODE", "hybrid").lower().strip()
if _raw_privacy == "local_only":
    PRIVACY_MODE = PrivacyMode.LOCAL_ONLY
elif _raw_privacy == "hybrid":
    PRIVACY_MODE = PrivacyMode.HYBRID
else:
    raise ValueError(
        f"Invalid PRIVACY_MODE '{_raw_privacy}'. Allowed values are strictly: 'hybrid' or 'local_only'."
    )

def validate_server_security():
    """Valida que el servidor no sea expuesto a interfaces de red externas sin autenticación."""
    is_loopback = HOST in ("127.0.0.1", "localhost", "::1")
    if not is_loopback and not API_KEY:
        raise RuntimeError(
            f"CRITICAL SECURITY CONFIGURATION ERROR: The server is configured to bind to "
            f"'{HOST}' (non-loopback) without an API_KEY. Set API_KEY in your environment to prevent unauthorized access."
        )

# Local LLM & Embedding Settings
LOCAL_ENGINE_TYPE = os.getenv("LOCAL_ENGINE_TYPE", "ollama").lower().strip().replace("-", "_")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/chat")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b")
LOCAL_EMBED_URL = os.getenv("LOCAL_EMBED_URL", "http://127.0.0.1:11434/api/embeddings")
LOCAL_EMBED_MODEL = os.getenv("LOCAL_EMBED_MODEL", "qwen3-embedding:8b")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", LOCAL_LLM_MODEL)

# Universal Cloud Fallback (Gemini / OpenAI / Anthropic / Groq / DeepSeek)
PROVIDER_DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "deepseek": "deepseek-chat"
}

CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini").lower().strip()
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "").strip()
if CLOUD_API_KEY in ("your_api_key_here", "your-api-key", "your_api_key"):
    CLOUD_API_KEY = ""

_custom_cloud_model = os.getenv("CLOUD_MODEL", "").strip()
CLOUD_MODEL = _custom_cloud_model or PROVIDER_DEFAULT_MODELS.get(CLOUD_PROVIDER, "gemini-2.0-flash")
CLOUD_MAX_TOKENS = int(os.getenv("CLOUD_MAX_TOKENS", 2048))

# Knowledge Base & Persistence Paths
SECOND_BRAIN_PATH = os.getenv("SECOND_BRAIN_PATH", "./knowledge_base")
INDEX_STORAGE_PATH = os.path.join(SECOND_BRAIN_PATH, "index.npz")

# Mathematical Routing Thresholds
RAG_CERTAINTY_THRESHOLD = float(os.getenv("RAG_CERTAINTY_THRESHOLD", 0.85))
RAG_MIN_THRESHOLD = float(os.getenv("RAG_MIN_THRESHOLD", 0.65))

# Network Security & Rate Limiting (Token Bucket)
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
RATE_LIMIT_CAPACITY = int(os.getenv("RATE_LIMIT_CAPACITY", "60"))
RATE_LIMIT_REFILL_RATE = float(os.getenv("RATE_LIMIT_REFILL_RATE", "1.0"))
SECURITY_HEADERS_ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "true").lower() in ("true", "1", "yes")

