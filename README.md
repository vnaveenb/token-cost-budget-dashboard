# Token + Cost Budget Dashboard

> A real-time LLM usage tracker with per-request cost attribution, budget enforcement, team/project-level quotas, and a live dashboard — works with any LiteLLM-supported provider.

![Status](https://img.shields.io/badge/Status-Planning-yellow)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white)

---

## Why this project?

Every LLM app leaks money silently. A prompt that's "just 1000 tokens" costs nothing — until it's called 10,000 times/day at $15/M tokens. You need:

1. **Per-request logging** — exact input/output tokens + cost for every call
2. **Real-time dashboards** — which endpoint / model / user is spending the most?
3. **Budget enforcement** — hard cutoffs before a runaway loop burns $500 overnight
4. **Alerts** — notify before budgets hit, not after

This is what production LLM teams build internally at Anthropic, OpenAI, and every startup spending >$1k/month on inference. Showing you've built this signals production maturity.

---

## Architecture Plan

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR LLM APP (Project 1, 4, etc.)           │
│                                                                 │
│  litellm.completion(model, messages, ...)                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │  LiteLLM callback hook
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              COST TRACKER MIDDLEWARE (tracker.py)                │
│                                                                 │
│  Intercepts every LLM call → logs:                              │
│    • model, provider                                            │
│    • input_tokens, output_tokens                                │
│    • cost (calculated from pricing table)                       │
│    • request_id, user_id, project_id, endpoint                  │
│    • timestamp, latency_ms                                      │
│    • success/failure                                            │
│                                                                 │
│  Budget check BEFORE call → reject if over budget               │
└───────────────────────────┬─────────────────────────────────────┘
                            │  Writes to
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SQLite (usage.db)                          │
│                                                                 │
│  Tables:                                                        │
│    usage_log    — one row per LLM call                          │
│    budgets      — per project/user/global limits                 │
│    alerts       — threshold rules + notification state          │
│    pricing      — cost per model per 1K input/output tokens     │
└───────────────────────────┬─────────────────────────────────────┘
                            │  Reads from
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI + HTML Dashboard                      │
│                                                                 │
│  /api/usage        — query usage by time range, model, project  │
│  /api/budgets      — CRUD budget limits                         │
│  /api/alerts       — configure budget alert thresholds          │
│  /dashboard        — live HTML dashboard (charts + tables)      │
└─────────────────────────────────────────────────────────────────┘
```

---

### Flow 1 — Logging a Request (Transparent to Caller)

```
Your app calls: litellm.completion(model="gemini/gemini-2.5-flash", ...)
    │
    ▼  LiteLLM success_callback (registered at startup)
    │
    ├── Extract: model, input_tokens, output_tokens, latency
    │
    ├── Look up cost from pricing table:
    │     gemini/gemini-2.5-flash → $0.15/1M input, $0.60/1M output
    │     cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000
    │
    ├── INSERT INTO usage_log (...)
    │
    └── Check budget: sum(cost) for this project this month vs limit
          ├── Under budget → proceed normally
          └── Over budget → log warning (or reject if pre-call check enabled)
```

---

### Flow 2 — Budget Enforcement (Pre-Call Gate)

```
Before LLM call:
    │
    ├── Query: SELECT SUM(cost) FROM usage_log
    │          WHERE project_id = ? AND timestamp >= start_of_period
    │
    ├── Compare against budget limit
    │     ├── < 80% → allow
    │     ├── 80-100% → allow + emit WARNING alert
    │     └── >= 100% → REJECT with BudgetExceededError
    │
    ▼  Caller gets clear error: "Budget exceeded: $48.50 / $50.00 for project X"
```

---

### Flow 3 — Dashboard Queries

```
GET /api/usage?range=7d&group_by=model

Response:
{
  "total_cost": 142.30,
  "total_tokens": { "input": 28_400_000, "output": 5_200_000 },
  "breakdown": [
    { "model": "gemini/gemini-2.5-flash", "cost": 89.50, "calls": 12400 },
    { "model": "gpt-4o",                   "cost": 52.80, "calls": 3200 }
  ],
  "daily": [
    { "date": "2026-05-18", "cost": 18.40 },
    { "date": "2026-05-19", "cost": 22.10 },
    ...
  ]
}
```

---

## Data Model

### usage_log

| Column | Type | Description |
|---|---|---|
| id | TEXT (UUID) | Primary key |
| timestamp | DATETIME | When the call was made |
| model | TEXT | LiteLLM model string |
| provider | TEXT | anthropic / openai / google / ollama |
| input_tokens | INTEGER | Prompt tokens |
| output_tokens | INTEGER | Completion tokens |
| cost_usd | REAL | Calculated cost |
| latency_ms | INTEGER | End-to-end call time |
| project_id | TEXT | Which project made the call |
| user_id | TEXT | Optional: which user |
| endpoint | TEXT | Optional: which API route triggered this |
| status | TEXT | success / error / timeout |
| error_msg | TEXT | NULL on success, error details on failure |

### budgets

| Column | Type | Description |
|---|---|---|
| id | TEXT | Primary key |
| scope | TEXT | "global" / "project" / "user" |
| scope_id | TEXT | project_id or user_id (null for global) |
| limit_usd | REAL | Maximum spend for the period |
| period | TEXT | "daily" / "weekly" / "monthly" |
| action | TEXT | "warn" / "reject" — what to do when exceeded |

### pricing

| Column | Type | Description |
|---|---|---|
| model | TEXT | LiteLLM model string |
| input_per_1m | REAL | $/1M input tokens |
| output_per_1m | REAL | $/1M output tokens |
| updated_at | DATETIME | When this pricing was last confirmed |

---

## Pricing Table (Bundled)

| Model | Input $/1M | Output $/1M |
|---|---|---|
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-haiku-4-5 | $0.80 | $4.00 |
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gemini/gemini-2.5-flash | $0.15 | $0.60 |
| gemini/gemini-2.5-pro | $1.25 | $10.00 |
| mistral/mistral-large | $2.00 | $6.00 |

Updated on new model releases — just add a row.

---

## Dashboard Features (Planned)

### Live HTML Dashboard (`/dashboard`)

1. **Cost over time** — line chart, daily/hourly granularity
2. **Cost by model** — pie chart showing spend distribution
3. **Top consumers** — table ranked by project/user/endpoint
4. **Budget gauges** — visual % used per budget (green/amber/red)
5. **Recent calls** — scrolling table of last 50 requests with token counts + cost
6. **Alerts panel** — active warnings and their trigger time

Tech: single HTML file with embedded JS (Chart.js), served by FastAPI. No build step, no React. Refreshes via polling or SSE.

---

## Key Concepts to Demonstrate

- **LiteLLM callbacks** — transparent logging without modifying application code
- **Cost calculation** — mapping model + tokens → dollars
- **Budget enforcement** — pre-call and post-call checks, configurable actions
- **Time-series aggregation** — SQL queries for dashboards (SUM, GROUP BY date/model)
- **Alert thresholds** — percentage-based warnings (80%, 90%, 100%)
- **Extensible pricing** — new models added to a table, not hardcoded
- **Separation of concerns** — the dashboard is a read layer; the tracker is a write layer

---

## Planned Project Structure

```
06-token-cost-budget-dashboard/
├── config.yaml              # Dashboard port, default budgets, pricing overrides
├── .env.example
├── requirements.txt
├── src/
│   ├── config.py            # Settings
│   ├── db.py                # SQLite connection + schema migrations
│   ├── models.py            # Pydantic models for usage_log, budget, alert
│   ├── pricing.py           # Pricing lookup table + cost calculator
│   ├── tracker.py           # LiteLLM callback — logs usage, checks budgets
│   ├── budget.py            # Budget CRUD + enforcement logic
│   ├── queries.py           # Aggregation queries for dashboard
│   ├── api.py               # FastAPI — /api/* routes
│   └── dashboard.py         # FastAPI — serves /dashboard HTML
├── static/
│   └── dashboard.html       # Single-file HTML dashboard (Chart.js)
├── schema/
│   └── init.sql             # SQLite schema DDL
├── tests/
│   ├── test_pricing.py      # Cost calculation tests
│   ├── test_tracker.py      # Logging tests
│   └── test_budget.py       # Budget enforcement tests
└── examples/
    ├── integrate.py          # How to wire into Project 1 or 4
    └── simulate_load.py      # Generate fake usage data for demo
```

---

## API Endpoints (Planned)

### Usage

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/usage` | Query usage with filters (range, model, project, user) |
| `GET` | `/api/usage/summary` | Aggregated stats (total cost, tokens, calls) |
| `GET` | `/api/usage/daily` | Daily breakdown for charting |
| `GET` | `/api/usage/by-model` | Cost grouped by model |

### Budgets

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/budgets` | List all budgets |
| `POST` | `/api/budgets` | Create a budget rule |
| `PUT` | `/api/budgets/{id}` | Update limit or action |
| `DELETE` | `/api/budgets/{id}` | Remove a budget |
| `GET` | `/api/budgets/status` | Current spend vs limit for all active budgets |

### Alerts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/alerts` | Active alerts |
| `POST` | `/api/alerts/configure` | Set threshold (e.g., alert at 80%) |

### Dashboard

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/dashboard` | Serves the live HTML dashboard |
| `GET` | `/api/health` | Service status |

---

## Integration with Other Projects

This dashboard is designed to **wrap around** any LiteLLM-using project:

```python
# In Project 1 or Project 4, at startup:
from cost_dashboard.src.tracker import register_callbacks

register_callbacks(project_id="rag-app", default_user="api")

# That's it. All LiteLLM calls are now logged automatically.
```

Or run as a standalone proxy:

```bash
# Standalone mode — your apps point to this as an LLM proxy
uvicorn src.api:app --port 8100
```

---

## Upgrade Path

This project is the foundation for:

- **Project 16 — Production Monitoring Loop**: adds drift detection (answer quality over time), latency percentile tracking, LLM-as-judge scoring, and auto-scaling triggers on top of this cost data.

---

## Build Order Within This Project

1. `schema/init.sql` + `src/db.py` — define tables, test migrations
2. `src/pricing.py` — cost calculator with bundled pricing table, test edge cases
3. `src/tracker.py` — LiteLLM callback, write to SQLite, test with mock calls
4. `src/budget.py` — enforcement logic (warn/reject), test thresholds
5. `src/queries.py` — aggregation SQL for dashboard data
6. `src/api.py` — FastAPI endpoints
7. `static/dashboard.html` — Chart.js visualization
8. `examples/simulate_load.py` — generate test data to demo the dashboard
9. `examples/integrate.py` — show how to plug into Project 1 or 4
