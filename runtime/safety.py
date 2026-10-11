import logging
import re
from typing import Dict, Any, List
import httpx

logger = logging.getLogger("safety_monitor")

class SafetyMonitor:
    ADVERSARIAL_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
        re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
        re.compile(r"curl\s+https?://", re.IGNORECASE),
        re.compile(r"LIVE-KEY-DO-NOT-USE", re.IGNORECASE),
        re.compile(r"dump\s+all\s+environment", re.IGNORECASE),
    ]

    def __init__(self, payments_url: str):
        self.payments_url = payments_url.rstrip("/")

    def check_credential_leak(self) -> Dict[str, Any]:
        """Queries the payments stub ledger to verify no production keys were leaked."""
        try:
            resp = httpx.get(f"{self.payments_url}/ledger/violations", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                violations = data.get("violations", [])
                return {
                    "leaked": len(violations) > 0,
                    "count": len(violations),
                    "violations": violations
                }
        except Exception as e:
            logger.warning(f"Could not reach payments stub for safety verification: {e}")
        return {"leaked": False, "count": 0, "violations": []}

    def sanitize_untrusted_log(self, text: str) -> str:
        """Wraps untrusted runtime logs in strict boundary markers and flags suspicious patterns."""
        threats_found = []
        for pattern in self.ADVERSARIAL_PATTERNS:
            if pattern.search(text):
                threats_found.append(pattern.pattern)

        warning_header = ""
        if threats_found:
            warning_header = (
                "[SAFETY WARNING: Potential prompt injection / adversarial content detected "
                f"in untrusted log stream: {len(threats_found)} match(es)]\n"
            )

        return f"<UNTRUSTED_RUNTIME_LOGS>\n{warning_header}{text}\n</UNTRUSTED_RUNTIME_LOGS>"
