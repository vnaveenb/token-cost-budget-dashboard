from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .budget import (
    BudgetExceededError,
    create_budget,
    delete_budget,
    get_all_budget_statuses,
    get_budget,
    list_budgets,
    update_budget,
)
from .config import get_config
from .db import configure as configure_db
from .db import init_db
from .models import BudgetCreate, BudgetUpdate
from .pricing import list_pricing, upsert_pricing
from .queries import (
    get_all_usage,
    get_daily_usage,
    get_recent_calls,
    get_top_consumers,
    get_usage_by_model,
    get_usage_summary,
)
from .tracker import register_callbacks

_static_dir = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    configure_db(cfg.database.path)
    init_db()
    register_callbacks()
    yield


app = FastAPI(
    title="Token + Cost Budget Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Usage ──────────────────────────────────────────────────────────────────────

@app.get("/api/usage")
def usage(
    range: int = Query(7, ge=1, le=365),
    model: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
):
    return get_all_usage(range, project_id, user_id, model, limit)


@app.get("/api/usage/summary")
def usage_summary(
    range: int = Query(7, ge=1, le=365),
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    model: Optional[str] = None,
):
    return get_usage_summary(range, project_id, user_id, model)


@app.get("/api/usage/daily")
def usage_daily(
    range: int = Query(30, ge=1, le=365),
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    return get_daily_usage(range, project_id, user_id)


@app.get("/api/usage/by-model")
def usage_by_model(range: int = Query(7, ge=1, le=365)):
    return get_usage_by_model(range)


@app.get("/api/usage/top-consumers")
def top_consumers(
    scope: str = Query("project", pattern="^(project|user)$"),
    range: int = Query(7, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
):
    return get_top_consumers(scope, range, limit)


@app.get("/api/usage/recent")
def recent_calls(limit: int = Query(50, ge=1, le=200)):
    return get_recent_calls(limit)


# ── Budgets — NOTE: /status must come before /{budget_id} ─────────────────────

@app.get("/api/budgets/status")
def budgets_status():
    return get_all_budget_statuses()


@app.get("/api/budgets")
def budgets_list():
    return list_budgets()


@app.post("/api/budgets", status_code=201)
def budgets_create(body: BudgetCreate):
    return create_budget(body.scope, body.scope_id, body.limit_usd, body.period, body.action)


@app.get("/api/budgets/{budget_id}")
def budgets_get(budget_id: str):
    result = get_budget(budget_id)
    if result is None:
        raise HTTPException(404, "Budget not found")
    return result


@app.put("/api/budgets/{budget_id}")
def budgets_update(budget_id: str, body: BudgetUpdate):
    result = update_budget(budget_id, body.limit_usd, body.action)
    if result is None:
        raise HTTPException(404, "Budget not found")
    return result


@app.delete("/api/budgets/{budget_id}", status_code=204)
def budgets_delete(budget_id: str):
    if not delete_budget(budget_id):
        raise HTTPException(404, "Budget not found")


# ── Alerts ─────────────────────────────────────────────────────────────────────

@app.get("/api/alerts")
def alerts_list():
    from .db import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT * FROM alerts").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/alerts/configure", status_code=201)
def alerts_configure(budget_id: str, threshold: float = 0.8):
    import uuid
    from .db import get_conn
    conn = get_conn()
    alert_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO alerts (id, budget_id, threshold) VALUES (?, ?, ?)",
        (alert_id, budget_id, threshold),
    )
    conn.commit()
    return {"id": alert_id, "budget_id": budget_id, "threshold": threshold}


# ── Pricing ────────────────────────────────────────────────────────────────────

@app.get("/api/pricing")
def pricing_list():
    return list_pricing()


@app.put("/api/pricing/{model:path}")
def pricing_update(model: str, input_per_1m: float, output_per_1m: float):
    upsert_pricing(model, input_per_1m, output_per_1m)
    return {"model": model, "input_per_1m": input_per_1m, "output_per_1m": output_per_1m}


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    html_path = _static_dir / "dashboard.html"
    if not html_path.exists():
        raise HTTPException(503, "dashboard.html not found")
    return FileResponse(str(html_path), media_type="text/html")


@app.get("/", include_in_schema=False)
def root():
    html_path = _static_dir / "dashboard.html"
    if not html_path.exists():
        return {"message": "Token + Cost Budget Dashboard API", "docs": "/docs"}
    return FileResponse(str(html_path), media_type="text/html")
