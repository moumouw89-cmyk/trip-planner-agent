from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .config import TRIPS_DIR
from .models import (
    BudgetItem,
    DayPlan,
    Hotel,
    ItineraryItem,
    TripPlan,
    TripRequest,
    ValidationIssue,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS trip_info (
    trip_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    start_date TEXT NOT NULL,
    days INTEGER NOT NULL,
    budget REAL NOT NULL,
    origin TEXT,
    preferences TEXT,
    pace TEXT,
    total_cost REAL NOT NULL,
    summary TEXT,
    hotel_name TEXT,
    hotel_price REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lodging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id TEXT,
    name TEXT,
    price REAL,
    rating REAL,
    area TEXT,
    address TEXT,
    source TEXT,
    photo_url TEXT
);

CREATE TABLE IF NOT EXISTS days (
    day_no INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    theme TEXT,
    daily_cost REAL NOT NULL,
    daily_minutes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS itinerary_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_no INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    poi_id TEXT NOT NULL,
    poi_name TEXT NOT NULL,
    category TEXT,
    start TEXT,
    end TEXT,
    travel_minutes INTEGER,
    ticket REAL,
    note TEXT,
    guide_citation TEXT,
    kind TEXT DEFAULT 'poi',
    photo_url TEXT,
    lat REAL,
    lon REAL
);

CREATE TABLE IF NOT EXISTS budget_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    amount REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    day INTEGER
);

CREATE TABLE IF NOT EXISTS plan_versions (
    version INTEGER PRIMARY KEY,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT
);
"""


def new_trip_id(city: str, start_date: str) -> str:
    return f"trip_{start_date.replace('-', '')}_{city}_{uuid4().hex[:4]}"


class TripDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def save_plan(self, plan: TripPlan, reason: str = "initial") -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO trip_info
            (trip_id, city, start_date, days, budget, origin, preferences, pace, total_cost, summary,
             hotel_name, hotel_price, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.trip_id,
                plan.request.city,
                plan.request.start_date,
                plan.request.days,
                plan.request.budget,
                plan.request.origin,
                plan.request.preferences,
                plan.request.pace,
                plan.total_cost,
                plan.summary,
                plan.selected_hotel.name if plan.selected_hotel else None,
                plan.selected_hotel.price if plan.selected_hotel else None,
                plan.created_at,
            ),
        )
        self.conn.execute("DELETE FROM lodging")
        if plan.selected_hotel:
            hotel = plan.selected_hotel
            self.conn.execute(
                "INSERT INTO lodging (hotel_id, name, price, rating, area, address, source, photo_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    hotel.id,
                    hotel.name,
                    hotel.price,
                    hotel.rating,
                    hotel.area,
                    hotel.address,
                    hotel.source,
                    hotel.photo_url,
                ),
            )
        self.conn.execute("DELETE FROM days")
        self.conn.execute("DELETE FROM itinerary_items")
        self.conn.execute("DELETE FROM budget_items")
        self.conn.execute("DELETE FROM validation_issues")

        for day in plan.days:
            self.conn.execute(
                "INSERT INTO days (day_no, date, theme, daily_cost, daily_minutes) VALUES (?, ?, ?, ?, ?)",
                (day.day, day.date, day.theme, day.daily_cost, day.daily_minutes),
            )
            for item in day.items:
                self.conn.execute(
                    """
                    INSERT INTO itinerary_items
                    (day_no, seq, poi_id, poi_name, category, start, end,
                     travel_minutes, ticket, note, guide_citation, kind, photo_url, lat, lon)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.day,
                        item.seq,
                        item.poi_id,
                        item.poi_name,
                        item.category,
                        item.start,
                        item.end,
                        item.travel_minutes,
                        item.ticket,
                        item.note,
                        item.guide_citation,
                        item.kind,
                        item.photo_url,
                        item.lat,
                        item.lon,
                    ),
                )
        for item in plan.budget_items:
            self.conn.execute(
                "INSERT INTO budget_items (category, label, amount) VALUES (?, ?, ?)",
                (item.category, item.label, item.amount),
            )
        for issue in plan.issues:
            self.conn.execute(
                "INSERT INTO validation_issues (code, severity, message, day) VALUES (?, ?, ?, ?)",
                (issue.code, issue.severity, issue.message, issue.day),
            )
        version = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM plan_versions"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO plan_versions (version, plan_json, created_at, reason) VALUES (?, ?, ?, ?)",
            (
                version,
                json.dumps(plan.to_dict(), ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
                reason,
            ),
        )
        self.conn.commit()
        plan.version = version

    def load_plan(self) -> TripPlan | None:
        def rows(query: str) -> list[dict]:
            cursor = self.conn.execute(query)
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

        info_rows = rows("SELECT * FROM trip_info LIMIT 1")
        if not info_rows:
            return None
        info = info_rows[0]
        request = TripRequest(
            city=info["city"],
            start_date=info["start_date"],
            days=int(info["days"]),
            budget=float(info["budget"]),
            origin=info.get("origin") or "",
            preferences=info.get("preferences") or "",
            pace=info.get("pace") or "balanced",
            raw_text="",
        )

        selected_hotel = None
        try:
            lodging = rows("SELECT * FROM lodging LIMIT 1")
        except sqlite3.OperationalError:
            lodging = []
        if lodging:
            hotel = lodging[0]
            selected_hotel = Hotel(
                id=hotel.get("hotel_id") or "",
                city=info["city"],
                name=hotel.get("name") or "",
                price=float(hotel.get("price") or 0),
                rating=float(hotel.get("rating") or 0),
                area=hotel.get("area") or "",
                lat=0,
                lon=0,
                address=hotel.get("address") or "",
                source=hotel.get("source") or "local",
                photo_url=hotel.get("photo_url") or "",
            )

        day_rows = rows("SELECT * FROM days ORDER BY day_no")
        item_rows = rows("SELECT * FROM itinerary_items ORDER BY day_no, seq")
        days = []
        for day_row in day_rows:
            items = [
                ItineraryItem(
                    day=int(item["day_no"]),
                    seq=int(item["seq"]),
                    poi_id=item.get("poi_id") or "",
                    poi_name=item.get("poi_name") or "",
                    category=item.get("category") or "",
                    start=item.get("start") or "",
                    end=item.get("end") or "",
                    travel_minutes=int(item.get("travel_minutes") or 0),
                    ticket=float(item.get("ticket") or 0),
                    note=item.get("note") or "",
                    guide_citation=item.get("guide_citation") or "",
                    kind=item.get("kind") or "poi",
                    photo_url=item.get("photo_url") or "",
                    lat=float(item.get("lat") or 0),
                    lon=float(item.get("lon") or 0),
                )
                for item in item_rows
                if int(item["day_no"]) == int(day_row["day_no"])
            ]
            days.append(
                DayPlan(
                    day=int(day_row["day_no"]),
                    date=day_row["date"],
                    theme=day_row.get("theme") or "",
                    items=items,
                    daily_cost=float(day_row.get("daily_cost") or 0),
                    daily_minutes=int(day_row.get("daily_minutes") or 0),
                )
            )

        budget_items = [
            BudgetItem(
                category=row["category"],
                label=row["label"],
                amount=float(row["amount"]),
            )
            for row in rows("SELECT * FROM budget_items ORDER BY id")
        ]
        issues = [
            ValidationIssue(
                code=row["code"],
                severity=row["severity"],
                message=row["message"],
                day=int(row["day"]) if row.get("day") is not None else None,
            )
            for row in rows("SELECT * FROM validation_issues ORDER BY id")
        ]
        versions = rows("SELECT * FROM plan_versions ORDER BY version DESC LIMIT 1")
        plan = TripPlan(
            trip_id=info["trip_id"],
            request=request,
            days=days,
            budget_items=budget_items,
            total_cost=float(info.get("total_cost") or 0),
            issues=issues,
            summary=info.get("summary") or "",
            created_at=info.get("created_at") or "",
            version=int(versions[0]["version"]) if versions else 1,
            hotel_options=[selected_hotel] if selected_hotel else [],
            selected_hotel=selected_hotel,
            db_path=str(self.path),
        )
        return plan

    def versions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version, created_at, reason FROM plan_versions ORDER BY version"
        ).fetchall()
        return [
            {"version": row[0], "created_at": row[1], "reason": row[2]}
            for row in rows
        ]


class TripRepository:
    def __init__(self, directory: str | Path = TRIPS_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(self, plan: TripPlan, reason: str = "initial") -> Path:
        path = self.directory / f"{plan.trip_id}.db"
        db = TripDatabase(path)
        try:
            db.save_plan(plan, reason=reason)
        finally:
            db.close()
        plan.db_path = str(path)
        return path

    def list_trips(self) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob("trip_*.db"), reverse=True):
            try:
                conn = sqlite3.connect(path)
                row = conn.execute(
                    "SELECT trip_id, city, start_date, days, budget, total_cost, summary, "
                    "hotel_name, hotel_price FROM trip_info"
                ).fetchone()
                conn.close()
                if row:
                    result.append(
                        {
                            "trip_id": row[0],
                            "city": row[1],
                            "start_date": row[2],
                            "days": row[3],
                            "budget": row[4],
                            "total_cost": row[5],
                            "summary": row[6],
                            "hotel_name": row[7],
                            "hotel_price": row[8],
                            "db_path": str(path),
                        }
                    )
            except Exception:
                continue
        return result

    def load(self, trip_id: str) -> TripPlan | None:
        path = self.directory / f"{trip_id}.db"
        if not path.exists():
            return None
        db = TripDatabase(path)
        try:
            return db.load_plan()
        finally:
            db.close()

    def delete(self, trip_id: str) -> bool:
        path = self.directory / f"{trip_id}.db"
        if not path.exists():
            return False
        path.unlink()
        return True

    def schema(self, trip_id: str) -> list[str]:
        path = self.directory / f"{trip_id}.db"
        if not path.exists():
            return []
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]
