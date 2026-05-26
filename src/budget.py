from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_conn


class BudgetExceededError(Exception):
    def __init__(self, message: str, budget_id: str, spent: float, limit: float):
        super().__init__(message)
        self.budget_id = budget_id
        self.spent = spent
        self.limit = limit


def _period_start(period: str) -> str:
    now = datetime.now(timezone.utc)
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    elif period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown period: {period}")
    return start.isoformat()


def _get_spent(scope: str, scope_id: Optional[str], period: str) -> float:
    period_start = _period_start(period)
    conn = get_conn()
    if scope == "global":
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_log "
            "WHERE timestamp >= ? AND status = 'success'",
            (period_start,),
        ).fetchone()
    elif scope == "project":
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_log "
            "WHERE project_id = ? AND timestamp >= ? AND status = 'success'",
            (scope_id, period_start),
        ).fetchone()
    elif scope == "user":
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_log "
            "WHERE user_id = ? AND timestamp >= ? AND status = 'success'",
            (scope_id, period_start),
        ).fetchone()
    else:
        return 0.0
    return float(row[0])


def check_budget(scope: str, scope_id: Optional[str]) -> list[dict]:
    conn = get_conn()
    if scope == "global":
        rows = conn.execute("SELECT * FROM budgets WHERE scope = 'global'").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE (scope = ? AND scope_id = ?) OR scope = 'global'",
            (scope, scope_id),
        ).fetchall()
    results = []
    for row in rows:
        budget = dict(row)
        spent = _get_spent(budget["scope"], budget.get("scope_id"), budget["period"])
        limit = budget["limit_usd"]
        pct = spent / limit if limit > 0 else 0.0
        results.append({
            "budget": budget,
            "spent": spent,
            "limit": limit,
            "pct": pct,
            "exceeded": pct >= 1.0,
        })
    return results


def enforce_budget(project_id: Optional[str], user_id: Optional[str]) -> None:
    """Check all applicable budgets. Raises BudgetExceededError if action='reject' and exceeded."""
    checks: list[dict] = []
    checks.extend(check_budget("global", None))
    if project_id:
        checks.extend(check_budget("project", project_id))
    if user_id:
        checks.extend(check_budget("user", user_id))

    for c in checks:
        b = c["budget"]
        if c["exceeded"] and b["action"] == "reject":
            raise BudgetExceededError(
                f"Budget exceeded: ${c['spent']:.4f} / ${c['limit']:.2f} "
                f"for {b['scope']} {b.get('scope_id') or 'global'} ({b['period']})",
                budget_id=b["id"],
                spent=c["spent"],
                limit=c["limit"],
            )


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_budget(
    scope: str,
    scope_id: Optional[str],
    limit_usd: float,
    period: str,
    action: str = "warn",
) -> dict:
    row_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        "INSERT INTO budgets VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, scope, scope_id, limit_usd, period, action),
    )
    conn.commit()
    return {"id": row_id, "scope": scope, "scope_id": scope_id,
            "limit_usd": limit_usd, "period": period, "action": action}


def list_budgets() -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM budgets").fetchall()]


def get_budget(budget_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()
    return dict(row) if row else None


def update_budget(
    budget_id: str,
    limit_usd: Optional[float],
    action: Optional[str],
) -> Optional[dict]:
    conn = get_conn()
    if limit_usd is not None:
        conn.execute("UPDATE budgets SET limit_usd = ? WHERE id = ?", (limit_usd, budget_id))
    if action is not None:
        conn.execute("UPDATE budgets SET action = ? WHERE id = ?", (action, budget_id))
    conn.commit()
    return get_budget(budget_id)


def delete_budget(budget_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
    conn.commit()
    return cur.rowcount > 0


def get_all_budget_statuses() -> list[dict]:
    budgets = list_budgets()
    results = []
    for b in budgets:
        spent = _get_spent(b["scope"], b.get("scope_id"), b["period"])
        limit = b["limit_usd"]
        pct = spent / limit if limit > 0 else 0.0
        results.append({
            "budget": b,
            "spent_usd": round(spent, 6),
            "remaining_usd": round(max(0.0, limit - spent), 6),
            "pct_used": round(pct * 100, 1),
            "exceeded": pct >= 1.0,
        })
    return results
