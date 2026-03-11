import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-sonnet-4-5-20250929")
MAX_TURNS = int(os.getenv("MAX_TURNS", "10"))
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "pearscaff.db")
CHROMA_PATH = os.getenv("CHROMA_PATH", "chroma_data")

# Gmail OAuth (API-based transport)
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
GMAIL_POLL_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "300"))

# Memory backend
MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "sqlite")  # "mem0" | "sqlite"
NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# LangSmith observability
LANGSMITH_ENABLED = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "pears")
