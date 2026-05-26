from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class DatabaseConfig(BaseModel):
    path: str = "./data/usage.db"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8100
    reload: bool = False


class DefaultBudgetConfig(BaseModel):
    global_monthly_limit_usd: Optional[float] = None
    warn_threshold: float = 0.8


class AppConfig(BaseModel):
    database: DatabaseConfig = DatabaseConfig()
    server: ServerConfig = ServerConfig()
    defaults: DefaultBudgetConfig = DefaultBudgetConfig()


_config: AppConfig | None = None


def get_config(path: str = "config.yaml") -> AppConfig:
    global _config
    if _config is None:
        _config = _load(path)
    return _config


def reload_config(path: str = "config.yaml") -> AppConfig:
    global _config
    _config = _load(path)
    return _config


def _load(path: str) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / path
    if config_path.exists():
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}
        return AppConfig(**data)
    return AppConfig()
