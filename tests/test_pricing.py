from __future__ import annotations

import pytest

import src.db as db_mod
from src.db import close_conn, configure as configure_db, init_db
from src.pricing import calculate_cost, get_pricing, upsert_pricing


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    configure_db(tmp_path / "test.db")
    init_db()
    yield
    close_conn()
    # Reset so next test gets a fresh configure
    db_mod._DB_PATH = None


def test_cost_gpt4o_input_only():
    cost = calculate_cost("gpt-4o", 1_000_000, 0)
    assert abs(cost - 2.50) < 1e-9


def test_cost_gpt4o_output_only():
    cost = calculate_cost("gpt-4o", 0, 1_000_000)
    assert abs(cost - 10.00) < 1e-9


def test_cost_mixed_tokens():
    # gemini-2.5-flash: $0.15/1M in, $0.60/1M out
    cost = calculate_cost("gemini/gemini-2.5-flash", 500_000, 200_000)
    expected = (500_000 * 0.15 + 200_000 * 0.60) / 1_000_000
    assert abs(cost - expected) < 1e-9


def test_cost_zero_tokens():
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_unknown_model_returns_zero():
    cost = calculate_cost("some-unknown-model-xyz-999", 1000, 500)
    assert cost == 0.0


def test_prefix_match_versioned_model():
    # LiteLLM sometimes appends a date suffix
    cost = calculate_cost("claude-sonnet-4-6-20250514", 1_000_000, 0)
    assert abs(cost - 3.00) < 1e-9


def test_prefix_match_haiku():
    cost = calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_upsert_overrides_pricing():
    upsert_pricing("test-model", 5.00, 20.00)
    inp, out = get_pricing("test-model")
    assert inp == 5.00
    assert out == 20.00


def test_upsert_updates_existing():
    upsert_pricing("gpt-4o", 9.99, 9.99)
    inp, out = get_pricing("gpt-4o")
    assert inp == 9.99
    assert out == 9.99


def test_db_lookup_takes_priority_over_fallback():
    # Override gpt-4o-mini with a custom rate
    upsert_pricing("gpt-4o-mini", 1.00, 2.00)
    cost = calculate_cost("gpt-4o-mini", 1_000_000, 0)
    assert abs(cost - 1.00) < 1e-9


def test_claude_sonnet_pricing():
    cost = calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    expected = (3.00 + 15.00)
    assert abs(cost - expected) < 1e-9
