CREATE TABLE IF NOT EXISTS usage_log (
    id            TEXT PRIMARY KEY,
    timestamp     TEXT NOT NULL,
    model         TEXT NOT NULL,
    provider      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    project_id    TEXT,
    user_id       TEXT,
    endpoint      TEXT,
    status        TEXT NOT NULL DEFAULT 'success',
    error_msg     TEXT
);

CREATE TABLE IF NOT EXISTS budgets (
    id        TEXT PRIMARY KEY,
    scope     TEXT NOT NULL,
    scope_id  TEXT,
    limit_usd REAL NOT NULL,
    period    TEXT NOT NULL,
    action    TEXT NOT NULL DEFAULT 'warn'
);

CREATE TABLE IF NOT EXISTS pricing (
    model          TEXT PRIMARY KEY,
    input_per_1m   REAL NOT NULL,
    output_per_1m  REAL NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id           TEXT PRIMARY KEY,
    budget_id    TEXT NOT NULL REFERENCES budgets(id),
    threshold    REAL NOT NULL DEFAULT 0.8,
    triggered    INTEGER NOT NULL DEFAULT 0,
    triggered_at TEXT,
    message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_project   ON usage_log(project_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_user      ON usage_log(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_model     ON usage_log(model, timestamp);
