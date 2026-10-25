from __future__ import annotations

import pytest

from trip_planner.poi import POIRepository
from trip_planner.rag import GuideIndex


@pytest.fixture()
def poi_repo() -> POIRepository:
    return POIRepository()


@pytest.fixture()
def guide_index(tmp_path) -> GuideIndex:
    return GuideIndex(db_path=tmp_path / "guides.db")
