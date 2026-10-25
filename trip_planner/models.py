from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TripRequest:
    city: str
    start_date: str
    days: int
    budget: float
    origin: str = "深圳"
    preferences: str = ""
    pace: str = "balanced"
    must_visit: list[str] = field(default_factory=list)
    hotel_id: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class POI:
    id: str
    name: str
    category: str
    lat: float
    lon: float
    visit_minutes: int
    ticket: float
    open: str
    close: str
    closed_days: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    area: str = ""
    score: float = 4.0
    description: str = ""
    photo_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hotel:
    id: str
    city: str
    name: str
    price: float
    rating: float
    area: str
    lat: float
    lon: float
    tags: list[str] = field(default_factory=list)
    address: str = ""
    source: str = "local"
    photo_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ItineraryItem:
    day: int
    seq: int
    poi_id: str
    poi_name: str
    category: str
    start: str
    end: str
    travel_minutes: int
    ticket: float
    note: str = ""
    guide_citation: str = ""
    kind: str = "poi"
    photo_url: str = ""
    lat: float = 0.0
    lon: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DayPlan:
    day: int
    date: str
    theme: str
    items: list[ItineraryItem] = field(default_factory=list)
    daily_cost: float = 0.0
    daily_minutes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class BudgetItem:
    category: str
    label: str
    amount: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    code: str
    severity: str
    message: str
    day: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TripPlan:
    trip_id: str
    request: TripRequest
    days: list[DayPlan]
    budget_items: list[BudgetItem]
    total_cost: float
    issues: list[ValidationIssue] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    hotel_options: list[Hotel] = field(default_factory=list)
    selected_hotel: Hotel | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    db_path: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "request": self.request.to_dict(),
            "days": [day.to_dict() for day in self.days],
            "budget_items": [item.to_dict() for item in self.budget_items],
            "total_cost": self.total_cost,
            "issues": [issue.to_dict() for issue in self.issues],
            "citations": self.citations,
            "hotel_options": [hotel.to_dict() for hotel in self.hotel_options],
            "selected_hotel": self.selected_hotel.to_dict() if self.selected_hotel else None,
            "trace": self.trace,
            "summary": self.summary,
            "created_at": self.created_at,
            "db_path": self.db_path,
            "version": self.version,
        }
