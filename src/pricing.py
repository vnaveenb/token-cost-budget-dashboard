from __future__ import annotations

import logging
from datetime import datetime, timezone

from .db import get_conn

logger = logging.getLogger(__name__)

FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":       (3.00, 15.00),
    "claude-haiku-4-5":        (0.80,  4.00),
    "gpt-4o":                  (2.50, 10.00),
    "gpt-4o-mini":             (0.15,  0.60),
    "gemini/gemini-2.5-flash": (0.15,  0.60),
    "gemini/gemini-2.5-pro":   (1.25, 10.00),
    "mistral/mistral-large":   (2.00,  6.00),
}


def get_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_1m, output_per_1m) for a model.

    Tries DB first, then prefix-match against fallback table,
    then returns (0.0, 0.0) with a warning.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT input_per_1m, output_per_1m FROM pricing WHERE model = ?", (model,)
    ).fetchone()
    if row:
        return float(row["input_per_1m"]), float(row["output_per_1m"])

    # Prefix-match handles date-suffixed model names from LiteLLM
    for key, (inp, out) in FALLBACK_PRICING.items():
        if model == key or model.startswith(key) or key in model:
            return inp, out

    logger.warning("Unknown model pricing: %s — cost will be $0.00", model)
    return 0.0, 0.0


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = get_pricing(model)
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


def upsert_pricing(model: str, input_per_1m: float, output_per_1m: float) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO pricing VALUES (?, ?, ?, ?)",
        (model, input_per_1m, output_per_1m, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def list_pricing() -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM pricing ORDER BY model").fetchall()]
