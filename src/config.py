"""Runtime configuration. Everything env-driven so no secrets live in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"
GOLD = DATA / "gold" / "gold_set.json"

APPS_YAML = DATA / "apps.yaml"

# Pass 1 output is FROZEN. Pass 2 writes elsewhere by design -- see CLAUDE.md
# rule 1. Without a preserved "before" snapshot the accuracy-delta story, which
# is the highest-weighted part of the rubric, cannot be reconstructed.
PASS1_JSON = OUT / "pass1.json"
TRIAGE_JSON = OUT / "triage.json"
PASS2_JSON = OUT / "pass2.json"
ACCURACY_JSON = OUT / "accuracy.json"
HUMAN_QUEUE_JSON = OUT / "human_queue.json"
REPORT_HTML = OUT / "report.html"


@dataclass(frozen=True)
class Settings:
    fetch_backend: str = os.getenv("FETCH_BACKEND", "stub")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    composio_api_key: str | None = os.getenv("COMPOSIO_API_KEY")
    model: str = os.getenv("MODEL", "claude-sonnet-4-5")
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "6"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "30"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "composio-app-research/0.1 (take-home research pipeline)",
    )

    def require_llm(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY unset. Use FETCH_BACKEND=stub for a "
                "credential-free dry run, or set the key in .env."
            )
        return self.anthropic_api_key


settings = Settings()

OUT.mkdir(parents=True, exist_ok=True)
