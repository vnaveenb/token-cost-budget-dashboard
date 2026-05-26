from __future__ import annotations

import uvicorn

from .api import app  # noqa: F401 — re-exported for uvicorn string reference
from .config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "src.api:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=cfg.server.reload,
    )


if __name__ == "__main__":
    main()
