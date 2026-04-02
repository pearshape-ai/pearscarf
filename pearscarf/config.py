import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-sonnet-4-5-20250929")
MAX_TURNS = int(os.getenv("MAX_TURNS", "30"))
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Extraction
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", MODEL)
EXTRACTION_MAX_TOKENS = int(os.getenv("EXTRACTION_MAX_TOKENS", "2048"))
EXTRACTION_TEMPERATURE = 0.0

# Postgres
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "pearscarf")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "pearscarf")

# Qdrant vector store
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

# Gmail OAuth (API-based transport)
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
GMAIL_POLL_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "300"))

# Linear
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
LINEAR_POLL_INTERVAL = int(os.getenv("LINEAR_POLL_INTERVAL", "300"))
LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID", "")

# Neo4j (knowledge graph)
NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# Curator
CURATOR_POLL_INTERVAL = int(os.getenv("CURATOR_POLL_INTERVAL", "30"))
CURATOR_CLAIM_TIMEOUT = int(os.getenv("CURATOR_CLAIM_TIMEOUT", "600"))

# Timezone (for Day node date derivation)
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")

# LangSmith observability
LANGSMITH_ENABLED = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "pears")
