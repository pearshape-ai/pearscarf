import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-sonnet-4-5-20250929")
MAX_TURNS = int(os.getenv("MAX_TURNS", "10"))
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
