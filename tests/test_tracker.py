from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

import src.db as db_mod
from src.budget import create_budget
from src.db import close_conn, configure as configure_db, get_conn, init_db
from src.tracker import _UsageLogger, register_callbacks


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    configure_db(tmp_path / "test.db")
    init_db()
    register_callbacks(project_id="test-proj")
    yield
    close_conn()
    db_mod._DB_PATH = None
    # Reset tracker globals so next test starts clean
    import src.tracker as t
    t._logger_instance = None
    t._DEFAULT_PROJECT_ID = None
    t._DEFAULT_USER_ID = None


def _make_response(prompt_tokens: int, completion_tokens: int):
    response = MagicMock()
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# ── Success logging ───────────────────────────────────────────────────────────

def test_success_writes_row():
    logger = _UsageLogger()
    kwargs = {
        "model": "gpt-4o",
        "litellm_params": {"metadata": {"project_id": "p1", "user_id": "alice"}},
    }
    now = _now()
    logger._write_success(kwargs, _make_response(1000, 200), now, now)
    conn = get_conn()
    row = conn.execute("SELECT * FROM usage_log WHERE project_id='p1'").fetchone()
    assert row is not None
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 200
    assert row["status"] == "success"
    assert row["model"] == "gpt-4o"


def test_success_calculates_cost():
    logger = _UsageLogger()
    kwargs = {
        "model": "gpt-4o",
        "litellm_params": {"metadata": {"project_id": "cost-test"}},
    }
    now = _now()
    # gpt-4o: $2.50/1M in, $10.00/1M out → 1M in = $2.50
    logger._write_success(kwargs, _make_response(1_000_000, 0), now, now)
    conn = get_conn()
    row = conn.execute("SELECT cost_usd FROM usage_log WHERE project_id='cost-test'").fetchone()
    assert abs(float(row["cost_usd"]) - 2.50) < 1e-6


def test_success_stores_latency():
    logger = _UsageLogger()
    kwargs = {"model": "gpt-4o-mini", "litellm_params": {"metadata": {}}}
    start = _now()
    end = start + datetime.timedelta(seconds=1)
    logger._write_success(kwargs, _make_response(100, 50), start, end)
    conn = get_conn()
    row = conn.execute("SELECT latency_ms FROM usage_log").fetchone()
    assert row["latency_ms"] >= 1000


def test_success_uses_default_project_id():
    import src.tracker as t
    t._DEFAULT_PROJECT_ID = "default-proj"
    logger = _UsageLogger()
    kwargs = {"model": "gpt-4o-mini", "litellm_params": {"metadata": {}}}
    now = _now()
    logger._write_success(kwargs, _make_response(100, 50), now, now)
    conn = get_conn()
    row = conn.execute("SELECT project_id FROM usage_log").fetchone()
    assert row["project_id"] == "default-proj"


# ── Failure logging ───────────────────────────────────────────────────────────

def test_failure_writes_error_row():
    logger = _UsageLogger()
    kwargs = {"model": "gpt-4o", "litellm_params": {"metadata": {"project_id": "err-proj"}}}
    now = _now()
    logger._write_failure(kwargs, Exception("timeout"), now, now)
    conn = get_conn()
    row = conn.execute("SELECT * FROM usage_log WHERE project_id='err-proj'").fetchone()
    assert row is not None
    assert row["status"] == "error"
    assert row["cost_usd"] == 0.0
    assert "timeout" in (row["error_msg"] or "")


def test_failure_zero_tokens():
    logger = _UsageLogger()
    kwargs = {"model": "claude-sonnet-4-6", "litellm_params": {"metadata": {}}}
    now = _now()
    logger._write_failure(kwargs, Exception("rate limit"), now, now)
    conn = get_conn()
    row = conn.execute("SELECT * FROM usage_log").fetchone()
    assert row["input_tokens"] == 0
    assert row["output_tokens"] == 0


# ── Provider extraction ───────────────────────────────────────────────────────

def test_success_extracts_provider_from_model_prefix():
    logger = _UsageLogger()
    kwargs = {
        "model": "gemini/gemini-2.5-flash",
        "litellm_params": {"metadata": {}},
    }
    now = _now()
    logger._write_success(kwargs, _make_response(100, 50), now, now)
    conn = get_conn()
    row = conn.execute("SELECT provider FROM usage_log").fetchone()
    assert row["provider"] == "gemini"


def test_success_extracts_anthropic_provider():
    logger = _UsageLogger()
    kwargs = {"model": "claude-sonnet-4-6", "litellm_params": {"metadata": {}}}
    now = _now()
    logger._write_success(kwargs, _make_response(100, 50), now, now)
    conn = get_conn()
    row = conn.execute("SELECT provider FROM usage_log").fetchone()
    assert row["provider"] == "anthropic"


# ── Budget enforcement in tracked_completion ──────────────────────────────────

@pytest.mark.asyncio
async def test_tracked_completion_raises_when_budget_exceeded(monkeypatch):
    from src.budget import BudgetExceededError
    from src.tracker import tracked_completion

    create_budget("project", "over-budget-proj", 0.0001, "monthly", "reject")

    # Seed spent amount directly
    import uuid
    conn = get_conn()
    conn.execute(
        "INSERT INTO usage_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "gpt-4o", "openai", 100, 50, 0.001, 500,
         "over-budget-proj", None, None, "success", None),
    )
    conn.commit()

    with pytest.raises(BudgetExceededError):
        await tracked_completion(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
            project_id="over-budget-proj",
        )
