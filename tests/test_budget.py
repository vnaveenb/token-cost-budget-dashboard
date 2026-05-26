from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import src.db as db_mod
from src.budget import (
    BudgetExceededError,
    _period_start,
    create_budget,
    delete_budget,
    enforce_budget,
    get_all_budget_statuses,
    get_budget,
    list_budgets,
    update_budget,
)
from src.db import close_conn, configure as configure_db, get_conn, init_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    configure_db(tmp_path / "test.db")
    init_db()
    yield
    close_conn()
    db_mod._DB_PATH = None


def _insert_cost(project_id: str, cost: float, user_id: str | None = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO usage_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            datetime.now(timezone.utc).isoformat(),
            "gpt-4o", "openai", 100, 50, cost, 500,
            project_id, user_id, None, "success", None,
        ),
    )
    conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_budget_returns_id():
    b = create_budget("project", "my-proj", 10.0, "monthly", "warn")
    assert "id" in b
    assert len(b["id"]) == 36  # UUID format


def test_list_budgets():
    create_budget("project", "p1", 5.0, "daily")
    create_budget("global", None, 100.0, "monthly")
    assert len(list_budgets()) == 2


def test_get_budget():
    b = create_budget("user", "alice", 20.0, "weekly", "reject")
    fetched = get_budget(b["id"])
    assert fetched is not None
    assert fetched["limit_usd"] == 20.0
    assert fetched["action"] == "reject"


def test_get_budget_missing_returns_none():
    assert get_budget("nonexistent-id") is None


def test_update_budget_limit():
    b = create_budget("project", "p1", 10.0, "monthly")
    updated = update_budget(b["id"], limit_usd=50.0, action=None)
    assert updated["limit_usd"] == 50.0


def test_update_budget_action():
    b = create_budget("project", "p1", 10.0, "monthly", "warn")
    updated = update_budget(b["id"], limit_usd=None, action="reject")
    assert updated["action"] == "reject"


def test_delete_budget():
    b = create_budget("project", "p1", 10.0, "monthly")
    assert delete_budget(b["id"]) is True
    assert get_budget(b["id"]) is None


def test_delete_budget_second_call_returns_false():
    b = create_budget("project", "p1", 10.0, "monthly")
    delete_budget(b["id"])
    assert delete_budget(b["id"]) is False


# ── Period start ──────────────────────────────────────────────────────────────

def test_period_start_daily():
    start = _period_start("daily")
    dt = datetime.fromisoformat(start)
    assert dt.hour == 0 and dt.minute == 0 and dt.second == 0


def test_period_start_monthly():
    start = _period_start("monthly")
    dt = datetime.fromisoformat(start)
    assert dt.day == 1


def test_period_start_weekly_within_7_days():
    from datetime import timedelta
    start = _period_start("weekly")
    dt = datetime.fromisoformat(start)
    now = datetime.now(timezone.utc)
    delta = now - dt.replace(tzinfo=timezone.utc)
    assert delta.days <= 7


def test_period_start_invalid_raises():
    with pytest.raises(ValueError):
        _period_start("yearly")


# ── Enforcement ───────────────────────────────────────────────────────────────

def test_enforce_reject_raises_when_exceeded():
    create_budget("project", "test-proj", 0.001, "monthly", "reject")
    _insert_cost("test-proj", 0.002)
    with pytest.raises(BudgetExceededError) as exc_info:
        enforce_budget("test-proj", None)
    assert exc_info.value.spent > exc_info.value.limit


def test_enforce_warn_does_not_raise_when_exceeded():
    create_budget("project", "warn-proj", 0.001, "monthly", "warn")
    _insert_cost("warn-proj", 0.002)
    # Should not raise
    enforce_budget("warn-proj", None)


def test_enforce_under_budget_does_not_raise():
    create_budget("project", "cheap-proj", 10.0, "monthly", "reject")
    _insert_cost("cheap-proj", 0.001)
    enforce_budget("cheap-proj", None)


def test_enforce_no_budgets_does_not_raise():
    enforce_budget("any-project", "any-user")


def test_global_budget_applies_to_all_projects():
    create_budget("global", None, 0.001, "monthly", "reject")
    _insert_cost("project-a", 0.001)
    _insert_cost("project-b", 0.001)
    with pytest.raises(BudgetExceededError):
        enforce_budget("project-c", None)


def test_project_budget_does_not_affect_other_projects():
    create_budget("project", "proj-a", 0.001, "monthly", "reject")
    _insert_cost("proj-a", 0.002)
    # proj-b should not be affected
    enforce_budget("proj-b", None)


def test_user_budget_enforcement():
    create_budget("user", "alice", 0.001, "monthly", "reject")
    _insert_cost("any-proj", 0.002, user_id="alice")
    with pytest.raises(BudgetExceededError):
        enforce_budget(None, "alice")


def test_budget_status_returns_spend():
    create_budget("project", "p1", 10.0, "monthly", "warn")
    _insert_cost("p1", 3.0)
    statuses = get_all_budget_statuses()
    assert len(statuses) == 1
    assert abs(statuses[0]["spent_usd"] - 3.0) < 1e-6
    assert statuses[0]["pct_used"] == 30.0
