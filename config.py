import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Automatically locate benchmark directory (supports bundled standalone or monorepo layouts)
if (BASE_DIR / "benchmark").exists():
    _DEFAULT_BENCHMARK = BASE_DIR / "benchmark"
elif (PROJECT_ROOT / "benchmark").exists():
    _DEFAULT_BENCHMARK = PROJECT_ROOT / "benchmark"
else:
    _DEFAULT_BENCHMARK = BASE_DIR / "benchmark"

BENCHMARK_DIR = Path(os.getenv("BENCHMARK_DIR", str(_DEFAULT_BENCHMARK))).resolve()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-pro")

# Digital Twin Runtime Configuration (0 enables dynamic ephemeral port allocation)
TWIN_BASE_DIR = Path(os.getenv("TWIN_BASE_DIR", "/tmp/digital_twins")).resolve()
DEFAULT_API_PORT = int(os.getenv("TWIN_API_PORT", "0"))
DEFAULT_PAYMENTS_PORT = int(os.getenv("TWIN_PAYMENTS_PORT", "0"))
DEFAULT_DB_PORT = int(os.getenv("TWIN_DB_PORT", "0"))

MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "10"))
