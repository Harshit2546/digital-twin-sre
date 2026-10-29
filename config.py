import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Automatically locate benchmark directory
if (BASE_DIR / "benchmark").exists():
    _DEFAULT_BENCHMARK = BASE_DIR / "benchmark"
elif (PROJECT_ROOT / "benchmark").exists():
    _DEFAULT_BENCHMARK = PROJECT_ROOT / "benchmark"
else:
    _DEFAULT_BENCHMARK = BASE_DIR / "benchmark"

BENCHMARK_DIR = Path(os.getenv("BENCHMARK_DIR", str(_DEFAULT_BENCHMARK))).resolve()

# Universal LLM Provider Configuration
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("MODEL_NAME", "deepseek/deepseek-chat"))
MODEL_NAME = LLM_MODEL  # Backward compatibility

# Provider API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# GitHub Token for PR Automation
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

# Runtime Configuration
TWIN_BASE_DIR = Path(os.getenv("TWIN_BASE_DIR", "/tmp/digital_twins")).resolve()
DEFAULT_API_PORT = int(os.getenv("TWIN_API_PORT", "0"))
DEFAULT_PAYMENTS_PORT = int(os.getenv("TWIN_PAYMENTS_PORT", "0"))
DEFAULT_DB_PORT = int(os.getenv("TWIN_DB_PORT", "0"))

MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "8"))
