from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SiteState(str, Enum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"
    vacation = "vacation"
    restricted = "restricted"


class ConnectivityStatus(BaseModel):
    online: bool
    conclusive: bool = True
    detail: str
    checked_at: str
    response_ms: int | None = None


class SiteStatus(BaseModel):
    id: str
    name: str
    url: str
    state: SiteState
    online: bool
    selectable: bool
    badge: Literal["en ligne", "hors ligne"]
    detail: str = ""
    checked_at: str
    response_ms: int | None = None
    default_enabled: bool = True


class CatalogSyncSupplierStatus(BaseModel):
    site_id: str
    site_name: str
    status: Literal["pending", "running", "ok", "unavailable", "failed", "missing"] = "pending"
    ok: bool = False
    item_count: int = 0
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    progress_percent: int = Field(default=0, ge=0, le=100)


class CatalogSyncStatus(BaseModel):
    running: bool = False
    queued: bool = False
    ready: bool = False
    global_progress_percent: int = Field(default=0, ge=0, le=100)
    current_supplier: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_completed_at: str | None = None
    last_success_at: str | None = None
    detail: str = ""
    suppliers: list[CatalogSyncSupplierStatus] = Field(default_factory=list)


class SearchRequest(BaseModel):
    model: Literal["1900"]
    keywords: str = Field(min_length=2, max_length=160)
    sites: list[str] = Field(min_length=1, max_length=8)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Les mots-clés sont vides.")
        return value


Availability = Literal["in_stock", "low_stock", "out_of_stock", "restocking", "unknown"]
Compatibility = Literal["compatible", "universal", "uncertain", "incompatible"]


class Offer(BaseModel):
    id: str
    site_id: str
    site_name: str
    title: str
    url: str
    image_url: str | None = None
    reference: str | None = None
    price: float | None = None
    currency: str | None = None
    availability: Availability = "unknown"
    availability_label: str = "À confirmer"
    models: list[str] = Field(default_factory=list)
    compatibility: Compatibility = "uncertain"
    query_confidence: float = 0.0
    raw_description: str = ""
    checked_at: str | None = None
    price_source: str = "unknown"
    availability_source: str = "unknown"
    previous_price: float | None = None
    previous_price_date: str | None = None
    price_trend: Literal["up", "down", "stable"] | None = None


class SiteSearchReport(BaseModel):
    site_id: str
    site_name: str
    state: Literal["ok", "empty", "error", "skipped"]
    result_count: int = 0
    pages_read: int = 0
    detail: str = ""


class SearchResponse(BaseModel):
    query: str
    model: Literal["1900"]
    generated_at: str
    offers: list[Offer]
    total_offers: int
    reports: list[SiteSearchReport]
    warnings: list[str]
    suggestions: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    ambiguity_reasons: list[str] = Field(default_factory=list)
    connectivity: ConnectivityStatus
