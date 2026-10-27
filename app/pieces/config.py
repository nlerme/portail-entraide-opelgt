from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.common.config import CONFIG_PATH, data_root, section
from app.common.version import VERSION


@dataclass(frozen=True)
class Settings:
    config_path: Path = CONFIG_PATH
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"
    public_url: str | None = None
    data_dir: Path = Path("data")
    timezone: str = "Europe/Paris"
    daily_restart_time: str = "02:00"
    weekly_catalog_update_day: str = "Monday,Wednesday,Friday"
    catalog_update_timeout_seconds: int = 21600
    request_timeout_seconds: float = 18
    connectivity_timeout_seconds: float = 4
    connectivity_cache_seconds: int = 20
    status_cache_seconds: int = 300
    status_probe_timeout_seconds: float = 6
    status_site_timeout_seconds: float = 14
    status_all_timeout_seconds: float = 20
    search_cache_seconds: int = 60
    detail_cache_seconds: int = 60
    translation_cache_seconds: int = 2592000
    max_pages_per_site: int = 0
    max_results_per_site: int = 0
    max_detail_pages_per_site: int = 8
    target_results_per_site: int = 30
    max_concurrent_sites: int = 2
    max_concurrent_pages_per_site: int = 2
    max_concurrent_details: int = 2
    search_site_timeout_seconds: float = 45
    search_all_timeout_seconds: float = 60
    circuit_breaker_failures: int = 3
    circuit_breaker_seconds: int = 120
    http_retries: int = 2
    default_requests_per_minute: int = 120
    respect_robots_txt: bool = True
    robots_cache_seconds: int = 86400
    disabled_sites: frozenset[str] = frozenset()
    default_enabled_sites: frozenset[str] = frozenset()
    user_agent: str = f"PortailEntraideOpelGT/{VERSION}"
    auth_login_url: str = ""
    auth_validation_url: str = ""
    auth_login_rate_limit_attempts: int = 5
    auth_login_rate_limit_window_seconds: int = 300
    auth_request_timeout_seconds: float = 30
    catalog_min_item_ratio: float = 0.7
    catalog_min_known_price_ratio: float = 0.5
    catalog_reject_zero_availability: bool = True
    catalog_min_baseline_items: int = 10

    @classmethod
    def from_config(cls) -> "Settings":
        server = section("server")
        auth = section("authentication")
        scraping = section("pieces", "scraping")
        validation = section("pieces", "catalog_validation")
        maintenance = section("maintenance")
        kwargs = {name: value for name, value in scraping.items() if name in cls.__dataclass_fields__}
        kwargs.update(
            host=str(server["host"]), port=int(server["port"]),
            log_level=str(server.get("log_level") or "info"),
            public_url=str(server.get("public_url") or "") or None,
            data_dir=data_root() / "pieces", timezone=str(maintenance["timezone"]),
            daily_restart_time=str(maintenance.get("weekly_catalog_update_time", "02:00")),
            weekly_catalog_update_day=str(maintenance.get("weekly_catalog_update_day", "Monday,Wednesday,Friday")),
            catalog_update_timeout_seconds=int(maintenance.get("catalog_update_timeout_seconds", 21600)),
            disabled_sites=frozenset(str(x) for x in scraping.get("disabled_sites", [])),
            default_enabled_sites=frozenset(str(x) for x in scraping.get("default_enabled_sites", [])),
            auth_login_url=str(auth["login_url"]), auth_validation_url=str(auth["validation_url"]),
            auth_login_rate_limit_attempts=int(auth["login_rate_limit_attempts"]),
            auth_login_rate_limit_window_seconds=int(auth["login_rate_limit_window_seconds"]),
            auth_request_timeout_seconds=float(auth["request_timeout_seconds"]),
            catalog_min_item_ratio=float(validation["min_item_ratio"]),
            catalog_min_known_price_ratio=float(validation["min_known_price_ratio"]),
            catalog_reject_zero_availability=bool(validation["reject_zero_availability"]),
            catalog_min_baseline_items=int(validation["min_baseline_items"]),
        )
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def validate(self) -> None:
        if self.timezone != "Europe/Paris":
            raise RuntimeError('maintenance.timezone doit rester fixé à "Europe/Paris".')
        if self.weekly_catalog_update_day != "Monday,Wednesday,Friday":
            raise RuntimeError('maintenance.weekly_catalog_update_day doit rester fixé à "Monday,Wednesday,Friday".')
        if self.daily_restart_time != "02:00":
            raise RuntimeError('maintenance.weekly_catalog_update_time doit rester fixé à "02:00".')
        if not self.auth_login_url.startswith("https://") or not self.auth_validation_url.startswith("https://"):
            raise RuntimeError("Les URL d'authentification doivent utiliser HTTPS.")


settings = Settings.from_config()
settings.data_dir.mkdir(parents=True, exist_ok=True)
