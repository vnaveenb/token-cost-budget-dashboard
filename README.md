# Token + Cost Budget Dashboard

> A real-time LLM usage tracker with per-request cost attribution, budget enforcement, team/project-level quotas, and a live dashboard — works with any LiteLLM-supported provider.

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-40%20passing-brightgreen)

---

## Why this project?

Every LLM app leaks money silently. A prompt that's "just 1000 tokens" costs nothing — until it's called 10,000 times/day at $15/M tokens. You need:

1. **Per-request logging** — exact input/output tokens + cost for every call
2. **Real-time dashboards** — which endpoint / model / user is spending the most?
3. **Budget enforcement** — hard cutoffs before a runaway loop burns $500 overnight
4. **Alerts** — notify before budgets hit, not after

This is what production LLM teams build internally at Anthropic, OpenAI, and every startup spending >$1k/month on inference. Showing you've built this signals production maturity.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed realistic demo data (500 calls across 30 days)
python examples/simulate_load.py --days 30 --calls 500

# 3. Start the dashboard server
uvicorn src.api:app --port 8100

# 4. Open the dashboard
open http://localhost:8100/dashboard
```

Or run with Docker:

```bash
docker build -t cost-dashboard .
docker run -p 8100:8100 -v dashboard_data:/app/data cost-dashboard
```

> Use a **named volume** (`dashboard_data`) rather than a bind mount so Project 04 can share the same volume and write its usage data into the same database.

---

## Live Integration with Project 04

Project 04 (Agent Tool Calls + Retries) ships with this tracker built in. On startup it calls `register_callbacks(project_id="04-agent-retries")` — every LLM reasoning step the agent makes is logged here automatically.

**In Docker**, both services share the `dashboard_data` named volume:

```
agent-tool-calls  ──writes──▶  dashboard_data:/app/data/usage.db  ◀──reads──  token-cost-dashboard
```

To run both together:

```bash
# Create the shared volume once
docker volume create dashboard_data

# Start the dashboard first (runs init_db)
cd 06-token-cost-budget-dashboard && docker compose up -d

# Start the agent (depends_on: token-cost-dashboard in Portainer stack)
cd ../04-agent-tool-calls-retries && docker compose up -d
```

The dashboard will show a `04-agent-retries` project entry under Top Consumers and Budget Gauges as soon as the first agent run completes.

---

## Architecture

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
│    pricing      — cost per model per 1M input/output tokens     │
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

## Pricing Table

| Model | Input $/1M | Output $/1M |
|---|---|---|
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-haiku-4-5 | $0.80 | $4.00 |
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gemini/gemini-2.5-flash | $0.15 | $0.60 |
| gemini/gemini-2.5-pro | $1.25 | $10.00 |
| mistral/mistral-large | $2.00 | $6.00 |

Seeded automatically on first run via `INSERT OR IGNORE`. Add new models via `PUT /api/pricing/{model}` or directly in `src/db.py`.

---

## Dashboard

### Live HTML Dashboard (`/dashboard`)

Single-file Chart.js dashboard — no build step, no React. Auto-refreshes every 30 seconds.

1. **KPI row** — total cost, total calls, input tokens, output tokens (7d)
2. **Cost over time** — line chart, 30-day daily granularity
3. **Cost by model** — doughnut chart showing spend distribution
4. **Budget gauges** — visual % used per budget (green < 80% / amber 80–100% / red ≥ 100%)
5. **Top consumers** — table ranked by project cost
6. **Recent calls** — scrolling table of last 50 requests with token counts, cost, latency, status

---

## Integration

```python
# In any LiteLLM-using project, at startup:
from src.config import get_config
from src.db import configure as configure_db, init_db
from src.tracker import register_callbacks

cfg = get_config()
configure_db(cfg.database.path)
init_db()
register_callbacks(project_id="rag-app", default_user="api")

# That's it. All litellm.completion() calls are now logged automatically.
```

For budget enforcement (rejects calls when over limit):

```python
from src.tracker import tracked_completion

response = await tracked_completion(
    model="gemini/gemini-2.5-flash",
    messages=[{"role": "user", "content": "..."}],
    project_id="rag-app",
    user_id="alice",
    endpoint="/query",
)
```

---

## API Endpoints

### Usage

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/usage` | Query usage with filters (range, model, project, user) |
| `GET` | `/api/usage/summary` | Aggregated stats (total cost, tokens, calls) |
| `GET` | `/api/usage/daily` | Daily breakdown for charting |
| `GET` | `/api/usage/by-model` | Cost grouped by model |
| `GET` | `/api/usage/top-consumers` | Ranked by project or user spend |
| `GET` | `/api/usage/recent` | Last N calls with full detail |

### Budgets

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/budgets` | List all budgets |
| `POST` | `/api/budgets` | Create a budget rule |
| `GET` | `/api/budgets/status` | Current spend vs limit for all budgets |
| `PUT` | `/api/budgets/{id}` | Update limit or action |
| `DELETE` | `/api/budgets/{id}` | Remove a budget |

### Alerts & Pricing

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/alerts` | Active alert configurations |
| `POST` | `/api/alerts/configure` | Set threshold (e.g., alert at 80%) |
| `GET` | `/api/pricing` | List all model pricing |
| `PUT` | `/api/pricing/{model}` | Override pricing for a model |

### Dashboard

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/dashboard` | Serves the live HTML dashboard |
| `GET` | `/api/health` | Service status |
| `GET` | `/docs` | Auto-generated OpenAPI docs |

---

## Project Structure

```
06-token-cost-budget-dashboard/
├── Dockerfile               # Standalone image; exposes port 8100
├── docker-compose.yml       # Mounts dashboard_data named volume (shared with project 04)
├── .github/
│   └── workflows/
│       └── ci.yml           # pytest → Docker build+push to GHCR
├── config.yaml              # Dashboard port, default budgets, pricing overrides
├── .env.example             # API key template
├── requirements.txt
├── pytest.ini
├── src/
│   ├── config.py            # Settings loader (YAML + defaults)
│   ├── db.py                # Thread-local SQLite + WAL mode + schema init
│   ├── models.py            # Pydantic v2 models
│   ├── pricing.py           # Cost calculator + pricing CRUD
│   ├── tracker.py           # LiteLLM CustomLogger + tracked_completion()
│   ├── budget.py            # Budget CRUD + enforce_budget() gate
│   ├── queries.py           # Aggregation SQL for dashboard
│   ├── api.py               # FastAPI routes
│   └── dashboard.py         # uvicorn entrypoint
├── static/
│   └── dashboard.html       # Single-file Chart.js dashboard
├── schema/
│   └── init.sql             # SQLite DDL (4 tables + indexes)
├── tests/
│   ├── test_pricing.py      # 11 cost calculation tests
│   ├── test_tracker.py      # 9 logging + callback tests
│   └── test_budget.py       # 20 enforcement + CRUD tests
└── examples/
    ├── integrate.py          # Drop-in integration for Project 1 or 4
    └── simulate_load.py      # Generate fake usage data for demo
```

---

## Testing

```bash
pytest tests/ -v
# 40 passed in ~7s
```

Tests use `tmp_path` fixtures — each test gets an isolated in-memory SQLite database. No mocking of the DB layer; all assertions hit real SQL.

---

## Key Concepts Demonstrated

- **LiteLLM callbacks** — transparent logging without modifying application code
- **Cost calculation** — mapping model + tokens → dollars with prefix-match for versioned model names
- **Budget enforcement** — pre-call gate via `tracked_completion()`, configurable warn/reject actions
- **Time-series aggregation** — SQL queries with `strftime`, `GROUP BY date/model`, `COALESCE(SUM, 0)`
- **Thread-safe SQLite** — `threading.local()` + WAL mode for concurrent FastAPI + callback writes
- **Extensible pricing** — new models added via API or DB row, not hardcoded
- **Separation of concerns** — dashboard is a read layer; tracker is a write layer

---

## Upgrade Path

This project is the foundation for:

- **Project 16 — Production Monitoring Loop**: adds drift detection (answer quality over time), latency percentile tracking, LLM-as-judge scoring, and auto-scaling triggers on top of this cost data.
