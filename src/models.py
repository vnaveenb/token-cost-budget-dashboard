from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class UsageRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    endpoint: Optional[str] = None
    status: Literal["success", "error", "timeout"] = "success"
    error_msg: Optional[str] = None


class BudgetCreate(BaseModel):
    scope: Literal["global", "project", "user"]
    scope_id: Optional[str] = None
    limit_usd: float
    period: Literal["daily", "weekly", "monthly"]
    action: Literal["warn", "reject"] = "warn"


class Budget(BudgetCreate):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class BudgetUpdate(BaseModel):
    limit_usd: Optional[float] = None
    action: Optional[Literal["warn", "reject"]] = None


class BudgetStatus(BaseModel):
    budget: Budget
    spent_usd: float
    remaining_usd: float
    pct_used: float
    exceeded: bool


class AlertConfig(BaseModel):
    budget_id: str
    threshold: float = 0.8


class Alert(AlertConfig):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    message: Optional[str] = None


class UsageSummary(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    period_start: str
    period_end: str


class DailyUsage(BaseModel):
    date: str
    cost_usd: float
    calls: int
    input_tokens: int
    output_tokens: int


class ModelUsage(BaseModel):
    model: str
    provider: str
    cost_usd: float
    calls: int
    input_tokens: int
    output_tokens: int


class PricingRow(BaseModel):
    model: str
    input_per_1m: float
    output_per_1m: float
    updated_at: datetime
