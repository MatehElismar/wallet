import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Wallet API
WALLET_API_TOKEN = os.getenv("WALLET_API_TOKEN", "")
WALLET_API_BASE_URL = os.getenv("WALLET_API_BASE_URL", "https://api.budgetbakers.com")

# LLM Provider Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # anthropic, openai, gemini, ollama
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")

# Email accounts are configured in email_accounts.json, not here.

# Pipeline
PIPELINE_RUN_INTERVAL_MINUTES = int(os.getenv("PIPELINE_RUN_INTERVAL_MINUTES", "15"))
PIPELINE_DRY_RUN = os.getenv("PIPELINE_DRY_RUN", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Database
STATE_DB_PATH = "wallet.db"
DEAD_LETTER_FILE = "dead_letter.jsonl"

# Constraints
MAX_BATCH_SIZE = 20
MAX_TOTAL_RECORDS = 20000
ALERT_RECORD_COUNT = 18000
MAX_FIELD_LENGTH = 255
RETRY_MAX_ATTEMPTS = 3
RATE_LIMIT_THRESHOLD = 300

def validate_config_for_phase(phase: int):
    """Validate required env vars based on implementation phase."""
    if phase >= 2:
        provider_keys = {
            "anthropic": ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
            "openai":    ("OPENAI_API_KEY",    OPENAI_API_KEY),
            "gemini":    ("GEMINI_API_KEY",     GEMINI_API_KEY),
            "ollama":    ("OLLAMA_BASE_URL",    OLLAMA_BASE_URL),
        }
        env_var, value = provider_keys.get(LLM_PROVIDER, ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY))
        if not value:
            raise ValueError(f"{env_var} is required for Phase 2+ with provider '{LLM_PROVIDER}'")

    if phase >= 3:
        if not WALLET_API_TOKEN:
            raise ValueError("WALLET_API_TOKEN is required for Phase 3+")

    logger.info(f"Configuration validated for Phase {phase} (provider: {LLM_PROVIDER})")
