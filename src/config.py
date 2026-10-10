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
    CLOUD_ONLY = "cloud_only"

# Server Settings (Localhost by default for secure isolation)
HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", 8000))

# Security & API Authentication (Optional for local dev, mandatory for shared/production)
API_KEY = os.getenv("API_KEY", "").strip()

# Privacy Guard Validation (Strict normalization & validation)
_raw_privacy = os.getenv("PRIVACY_MODE", "hybrid").lower().strip().replace("-", "_")
if _raw_privacy in ("local_only", "local", "strict"):
    PRIVACY_MODE = PrivacyMode.LOCAL_ONLY
elif _raw_privacy in ("cloud_only", "cloud"):
    PRIVACY_MODE = PrivacyMode.CLOUD_ONLY
elif _raw_privacy in ("hybrid", "auto", "default"):
    PRIVACY_MODE = PrivacyMode.HYBRID
else:
    logger.warning(f"⚠️ PRIVACY_MODE '{_raw_privacy}' desconocido. Aplicando 'local_only' por seguridad por defecto.")
    PRIVACY_MODE = PrivacyMode.LOCAL_ONLY

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
