"""
simulate_load.py — Seed the database with realistic fake usage data.

Usage:
    python examples/simulate_load.py [--days 30] [--calls 500]
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.db import configure as configure_db, get_conn, init_db

# (model, provider, input_$/1M, output_$/1M, weight)
MODELS = [
    ("gemini/gemini-2.5-flash", "google",    0.15,  0.60, 0.45),
    ("gpt-4o-mini",              "openai",    0.15,  0.60, 0.25),
    ("claude-haiku-4-5",         "anthropic", 0.80,  4.00, 0.15),
    ("gpt-4o",                   "openai",    2.50, 10.00, 0.08),
    ("claude-sonnet-4-6",        "anthropic", 3.00, 15.00, 0.05),
    ("mistral/mistral-large",    "mistral",   2.00,  6.00, 0.02),
]

PROJECTS   = ["rag-app", "agent-v1", "agent-v2", "internal-tools", "prod-api"]
USERS      = ["alice", "bob", "charlie", "diana", "eve", None]
ENDPOINTS  = ["/query", "/summarize", "/embed", "/chat", "/classify", None]


def simulate(days: int, total_calls: int) -> None:
    now = datetime.now(timezone.utc)
    conn = get_conn()
    rows = []

    for _ in range(total_calls):
        m = random.choices(MODELS, weights=[x[4] for x in MODELS])[0]
        model, provider, inp_rate, out_rate, _ = m

        # Exponential time distribution — recent data is denser
        days_back = min(random.expovariate(1 / 3), days)
        ts = now - timedelta(days=days_back, seconds=random.randint(0, 86400))

        # Log-normal token counts (right-skewed — most calls small, some large)
        input_tokens  = max(10,  int(random.lognormvariate(6.5, 1.2)))
        output_tokens = max(1,   int(random.lognormvariate(4.5, 1.0)))
        cost = (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000
        latency_ms = max(200, int(random.lognormvariate(7.0, 0.8)))

        status = "success" if random.random() > 0.03 else "error"
        error_msg = "API rate limit exceeded" if status == "error" else None
        if status == "error":
            cost = 0.0

        rows.append((
            str(uuid.uuid4()),
            ts.isoformat(),
            model, provider,
            input_tokens, output_tokens,
            round(cost, 8),
            latency_ms,
            random.choice(PROJECTS),
            random.choice(USERS),
            random.choice(ENDPOINTS),
            status,
            error_msg,
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO usage_log
           (id, timestamp, model, provider, input_tokens, output_tokens,
            cost_usd, latency_ms, project_id, user_id, endpoint, status, error_msg)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()

    total_cost = sum(r[6] for r in rows if r[11] == "success")
    print(f"Inserted {len(rows)} records spanning {days} days.")
    print(f"Total simulated cost: ${total_cost:.4f}")
    print(f"Dashboard: http://localhost:8100/dashboard")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed fake LLM usage data")
    parser.add_argument("--days",  type=int, default=30,  help="Time span in days")
    parser.add_argument("--calls", type=int, default=500, help="Number of records to insert")
    args = parser.parse_args()

    cfg = get_config()
    configure_db(cfg.database.path)
    init_db()
    simulate(args.days, args.calls)
