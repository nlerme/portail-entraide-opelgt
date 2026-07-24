from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator

from app.common.config import CONFIG_PATH, data_root, section


class Settings(BaseModel):
    config_path: Path = CONFIG_PATH
    bulletins_url: str
    login_url: str
    app_host: str
    app_port: int
    public_url: str
    log_level: str
    app_secret: str = "unused-common-session"
    data_dir: Path
    ocr_lang: str
    ocr_dpi: int
    ocr_mode: str
    ocr_text_threshold: int
    ocr_multipass: bool
    ocr_psm_main: int
    ocr_psm_sparse: int
    ocr_timeout_seconds: int
    ocr_workers: int
    ocr_workers_auto_cap: int
    http_timeout_seconds: int
    max_pdf_bytes: int
    user_agent: str
    login_rate_limit_attempts: int
    login_rate_limit_window_seconds: int
    session_max_age_seconds: int
    https_only_cookies: bool
    timezone: str
    weekly_restart_day: str = "Sun"
    weekly_restart_time: str
    admin_enabled: bool
    admin_username: str
    admin_password_hash: str = ""
    admin_session_max_age_seconds: int
    admin_log_tail_lines: int

    @field_validator("ocr_mode")
    @classmethod
    def validate_ocr_mode(cls, value: str) -> str:
        if value not in {"auto", "always", "never", "hybrid"}:
            raise ValueError("bulletins.ocr.mode doit valoir auto, always, never ou hybrid")
        return value

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bulletins.sqlite3"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdf"

    @property
    def logs_dir(self) -> Path:
        return data_root() / "logs"

    @property
    def host(self) -> str:
        return self.app_host

    @property
    def port(self) -> int:
        return self.app_port

    @classmethod
    def from_config(cls) -> "Settings":
        server = section("server")
        auth = section("authentication")
        admin = section("admin")
        sessions = section("sessions")
        remote = section("bulletins", "remote")
        ocr = section("bulletins", "ocr")
        network = section("bulletins", "network")
        maintenance = section("maintenance")
        return cls(
            bulletins_url=str(remote["bulletins_url"]),
            login_url=str(auth["login_url"]),
            app_host=str(server["host"]),
            app_port=int(server["port"]),
            public_url=str(server.get("public_url") or ""),
            log_level=str(server.get("log_level") or "info"),
            data_dir=data_root() / "bulletins",
            ocr_lang=str(ocr["lang"]),
            ocr_dpi=int(ocr["dpi"]),
            ocr_mode=str(ocr["mode"]),
            ocr_text_threshold=int(ocr["text_threshold"]),
            ocr_multipass=bool(ocr["multipass"]),
            ocr_psm_main=int(ocr["psm_main"]),
            ocr_psm_sparse=int(ocr["psm_sparse"]),
            ocr_timeout_seconds=int(ocr["timeout_seconds"]),
            ocr_workers=int(ocr["workers"]),
            ocr_workers_auto_cap=int(ocr["workers_auto_cap"]),
            http_timeout_seconds=int(network["http_timeout_seconds"]),
            max_pdf_bytes=int(network.get("max_pdf_bytes", 104857600)),
            user_agent=str(network["user_agent"]),
            login_rate_limit_attempts=int(auth["login_rate_limit_attempts"]),
            login_rate_limit_window_seconds=int(auth["login_rate_limit_window_seconds"]),
            session_max_age_seconds=int(sessions.get("duration_minutes", 30)) * 60,
            https_only_cookies=bool(auth.get("https_only_cookies", False)),
            timezone=str(maintenance["timezone"]),
            weekly_restart_time=str(maintenance.get("weekly_catalog_update_time", "00:00")),
            admin_enabled=bool(admin.get("enabled", True)),
            admin_username=str(admin.get("username", "admin")),
            admin_session_max_age_seconds=int(sessions.get("duration_minutes", 30)) * 60,
            admin_log_tail_lines=int(admin.get("log_tail_lines", 300)),
        )


settings = Settings.from_config()
