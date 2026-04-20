import os

# =========================
# 🔑 API KEYS
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")

# =========================
# 🤖 LLM CONFIGURATION
# =========================
USE_OPENAI = False  # True → OpenAI | False → Ollama

OPENAI_MODEL = "gpt-4o-mini"
OLLAMA_MODEL = "llama3"

# Select active model
MODEL_NAME = OPENAI_MODEL if USE_OPENAI else OLLAMA_MODEL

# =========================
# 📦 STORAGE CONFIG
# =========================
FAISS_INDEX_PATH = "faiss.index"
FAISS_META_PATH = FAISS_INDEX_PATH + "_meta.pkl"

# =========================
# 📁 APP CONFIG
# =========================
UPLOAD_DIR = "uploads"
MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64MB

# =========================
# ⚙️ RAG SETTINGS
# =========================
TOP_K = 3
SIMILARITY_THRESHOLD = 0.5

# =========================
# 🌐 OLLAMA CONFIG
# =========================
OLLAMA_URL = "http://localhost:11434/api/generate"

# =========================
# 🧠 OPENAI CONFIG
# =========================
OPENAI_BASE_URL = "https://api.openai.com/v1"
