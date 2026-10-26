from __future__ import annotations

import logging
import logging.handlers

import uvicorn

from app.common.config import data_root, section


def configure_logging() -> None:
    log_dir = data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "web.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, str(section("server").get("log_level", "info")).upper(), logging.INFO))
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)


def main() -> int:
    configure_logging()
    server = section("server")
    uvicorn.run(
        "app.main:app",
        host=str(server["host"]),
        port=int(server["port"]),
        log_level=str(server.get("log_level", "info")),
        access_log=True,
        ws="none",
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
