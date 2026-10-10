import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")

# Local LLM & Embedding Settings
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/chat")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b")
LOCAL_EMBED_URL = os.getenv("LOCAL_EMBED_URL", "http://127.0.0.1:11434/api/embeddings")
LOCAL_EMBED_MODEL = os.getenv("LOCAL_EMBED_MODEL", "qwen3-embedding:8b")

# Google Gemini Cloud Fallback
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Knowledge Base / Markdown Sync
SECOND_BRAIN_PATH = os.getenv("SECOND_BRAIN_PATH", "./knowledge_base")

# Mathematical Thresholds
RAG_CERTAINTY_THRESHOLD = float(os.getenv("RAG_CERTAINTY_THRESHOLD", 0.85))
RAG_MIN_THRESHOLD = float(os.getenv("RAG_MIN_THRESHOLD", 0.65))
