from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_conn


def get_usage_summary(
    range_days: int = 7,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    since = _days_ago(range_days)
    where, params = _build_where(since, project_id, user_id, model)
    conn = get_conn()
    row = conn.execute(
        f"""SELECT
              COALESCE(SUM(cost_usd), 0)      AS total_cost,
              COALESCE(SUM(input_tokens), 0)  AS total_input,
              COALESCE(SUM(output_tokens), 0) AS total_output,
              COUNT(*)                         AS total_calls
            FROM usage_log {where}""",
        params,
    ).fetchone()
    return {
        "total_cost_usd": round(float(row["total_cost"]), 6),
        "total_input_tokens": int(row["total_input"]),
        "total_output_tokens": int(row["total_output"]),
        "total_calls": int(row["total_calls"]),
        "period_start": since,
        "period_end": datetime.now(timezone.utc).isoformat(),
    }


def get_daily_usage(
    range_days: int = 30,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict]:
    since = _days_ago(range_days)
    where, params = _build_where(since, project_id, user_id, None)
    conn = get_conn()
    rows = conn.execute(
        f"""SELECT
              strftime('%Y-%m-%d', timestamp) AS date,
              COALESCE(SUM(cost_usd), 0)      AS cost_usd,
              COUNT(*)                         AS calls,
              COALESCE(SUM(input_tokens), 0)  AS input_tokens,
              COALESCE(SUM(output_tokens), 0) AS output_tokens
            FROM usage_log {where}
            GROUP BY date
            ORDER BY date ASC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_usage_by_model(range_days: int = 7) -> list[dict]:
    since = _days_ago(range_days)
    conn = get_conn()
    rows = conn.execute(
        """SELECT model, provider,
              COALESCE(SUM(cost_usd), 0)      AS cost_usd,
              COUNT(*)                         AS calls,
              COALESCE(SUM(input_tokens), 0)  AS input_tokens,
              COALESCE(SUM(output_tokens), 0) AS output_tokens
           FROM usage_log
           WHERE timestamp >= ? AND status = 'success'
           GROUP BY model
           ORDER BY cost_usd DESC""",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_top_consumers(
    scope: str = "project",
    range_days: int = 7,
    limit: int = 10,
) -> list[dict]:
    since = _days_ago(range_days)
    # scope is validated by the API layer — safe to use as column name
    col = "project_id" if scope == "project" else "user_id"
    conn = get_conn()
    rows = conn.execute(
        f"""SELECT {col} AS scope_id,
              COALESCE(SUM(cost_usd), 0)      AS cost_usd,
              COUNT(*)                         AS calls,
              COALESCE(SUM(input_tokens), 0)  AS input_tokens,
              COALESCE(SUM(output_tokens), 0) AS output_tokens
           FROM usage_log
           WHERE timestamp >= ? AND {col} IS NOT NULL AND status = 'success'
           GROUP BY {col}
           ORDER BY cost_usd DESC
           LIMIT ?""",
        (since, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_calls(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM usage_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_usage(
    range_days: int = 7,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    since = _days_ago(range_days)
    where, params = _build_where(since, project_id, user_id, model)
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM usage_log {where} ORDER BY timestamp DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _build_where(
    since: str,
    project_id: Optional[str],
    user_id: Optional[str],
    model: Optional[str],
) -> tuple[str, list]:
    clauses = ["timestamp >= ?", "status = 'success'"]
    params: list = [since]
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if model:
        clauses.append("model = ?")
        params.append(model)
    return "WHERE " + " AND ".join(clauses), params
