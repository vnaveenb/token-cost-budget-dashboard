"""
integrate.py — Drop-in cost tracking for any LiteLLM-using project.

3 lines at startup, then all litellm calls are automatically logged.
Use tracked_completion() instead of litellm.completion() for budget enforcement.

Usage:
    python examples/integrate.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.db import configure as configure_db, init_db
from src.tracker import register_callbacks, tracked_completion

# ── Setup (once at startup) ───────────────────────────────────────────────────

cfg = get_config()
configure_db(cfg.database.path)
init_db()
register_callbacks(project_id="demo-project", default_user="demo")

# ── Option A: tracked_completion — budget enforcement + logging ───────────────

async def demo_tracked():
    print("Option A: tracked_completion with budget enforcement")
    try:
        response = await tracked_completion(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": "What is 2+2? Answer in one word."}],
            project_id="demo-project",
            user_id="alice",
            endpoint="/demo",
        )
        print("Answer:", response.choices[0].message.content)
        print("Usage logged. View at http://localhost:8100/dashboard")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")


# ── Option B: existing litellm.completion() unchanged ────────────────────────
#
# Because register_callbacks() appends to litellm.callbacks, any existing
# litellm.completion() or litellm.acompletion() calls in your codebase are
# now automatically logged. No code changes needed.
#
# You only need tracked_completion() if you want pre-call budget enforcement.


if __name__ == "__main__":
    asyncio.run(demo_tracked())
