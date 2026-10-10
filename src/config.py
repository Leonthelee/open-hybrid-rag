import os
from dotenv import load_dotenv

load_dotenv()

# Server Settings (Localhost by default for security)
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))

# Security & API Authentication (Optional, empty string = open for local dev)
API_KEY = os.getenv("API_KEY", "").strip()

# Privacy Guard (local_only: never escalates to cloud, hybrid: allows cloud escalation)
PRIVACY_MODE = os.getenv("PRIVACY_MODE", "hybrid").lower().strip()

# Local LLM & Embedding Settings
# Engine format: "ollama" | "openai_compatible" (LM Studio, vLLM, LocalAI)
LOCAL_ENGINE_TYPE = os.getenv("LOCAL_ENGINE_TYPE", "ollama").lower().strip()
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
