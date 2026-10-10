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
# Engine format: "ollama" | "openai_compatible" (LM Studio, vLLM, LocalAI)
LOCAL_ENGINE_TYPE = os.getenv("LOCAL_ENGINE_TYPE", "ollama").lower().strip().replace("-", "_")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/chat")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b")
LOCAL_EMBED_URL = os.getenv("LOCAL_EMBED_URL", "http://127.0.0.1:11434/api/embeddings")
LOCAL_EMBED_MODEL = os.getenv("LOCAL_EMBED_MODEL", "qwen3-embedding:8b")

# Universal Cloud Fallback (Gemini / OpenAI / Anthropic / Groq / DeepSeek)
CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini").lower().strip()
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "").strip()
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "gemini-2.0-flash").strip()

# Knowledge Base & Persistence Paths
SECOND_BRAIN_PATH = os.getenv("SECOND_BRAIN_PATH", "./knowledge_base")
INDEX_STORAGE_PATH = os.path.join(SECOND_BRAIN_PATH, "index.npz")

# Mathematical Routing Thresholds
RAG_CERTAINTY_THRESHOLD = float(os.getenv("RAG_CERTAINTY_THRESHOLD", 0.85))
RAG_MIN_THRESHOLD = float(os.getenv("RAG_MIN_THRESHOLD", 0.65))
