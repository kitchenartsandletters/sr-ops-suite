"""
business_calendar.py

Business calendar logic for KAL sr-ops-suite.
Supports two locations with different baseline hours and shared holiday closures.

Locations:
    kal  — 1435 Lexington Ave, Mon–Sat, opens 10:00 AM ET
    nyfs — 111 Broadway, Tue–Sun, opens 12:00 PM ET

Holiday closures are shared across both locations.
Special open Sundays are location-scoped.

DB overrides (reports.business_calendar_overrides) always win over the
hardcoded baseline when location_id matches.
"""

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

# ─── Location config ──────────────────────────────────────────────────────────

LOCATION_KAL  = "kal"
LOCATION_NYFS = "nyfs"

LOCATION_OPEN_TIME = {
    LOCATION_KAL:  (10, 0),   # 10:00 AM ET
    LOCATION_NYFS: (12, 0),   # 12:00 PM ET
}

LOCATION_CLOSE_TIME = {
    LOCATION_KAL:  (9, 59),   # 9:59 AM ET next day
    LOCATION_NYFS: (11, 59),  # 11:59 AM ET next day
}

# Weekdays open by default (0=Mon, 1=Tue, ..., 6=Sun)
LOCATION_OPEN_WEEKDAYS = {
    LOCATION_KAL:  {0, 1, 2, 3, 4, 5},       # Mon–Sat
    LOCATION_NYFS: {1, 2, 3, 4, 5, 6},       # Tue–Sun
}

# ─── Hardcoded holiday closures (shared across both locations) ────────────────

HOLIDAY_CLOSURES = {
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 5, 24),  # Memorial Day (Sat)
    date(2025, 5, 25),  # Memorial Day (Sun — NYFS closed)
    date(2025, 5, 26),  # Memorial Day
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    date(2025, 12, 26), # Boxing Day

    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 5, 23),  # Memorial Day weekend (Sat)
    date(2026, 5, 24),  # Memorial Day weekend (Sun)
    date(2026, 5, 25),  # Memorial Day
    date(2026, 7, 4),   # Independence Day
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    date(2026, 12, 26), # Boxing Day
}

# Special open Sundays for KAL (Lexington) only
KAL_OPEN_SUNDAYS = {
    date(2026, 12, 6),
    date(2026, 12, 13),
    date(2026, 12, 20),
}


# ─── DB override cache ────────────────────────────────────────────────────────

_db_overrides_cache: dict[str, dict] = {}  # keyed by location_id


def _load_db_overrides(location_id: str) -> dict:
    """
    Fetch calendar overrides from Supabase for a given location.
    Returns {"holiday_closure": set[date], "special_open_sunday": set[date]}.
    Cached per location per process lifetime.
    """
    if location_id in _db_overrides_cache:
        return _db_overrides_cache[location_id]

    result = {"holiday_closure": set(), "special_open_sunday": set()}

    try:
        from services.supabase_client import supabase
        resp = (
            supabase
            .schema("reports")
            .table("business_calendar_overrides")
            .select("date, override_type")
            .eq("location_id", location_id)
            .execute()
        )
        for row in (resp.data or []):
            d = date.fromisoformat(row["date"])
            otype = row["override_type"]
            if otype in result:
                result[otype].add(d)
    except Exception as e:
        logging.warning(f"[calendar] Failed to load DB overrides for {location_id}: {e}")

    _db_overrides_cache[location_id] = result
    return result


def _clear_cache():
    """Clear the override cache (useful for testing)."""
    _db_overrides_cache.clear()


# ─── Core calendar logic ──────────────────────────────────────────────────────

def is_business_day(d: date, location_id: str = LOCATION_KAL) -> bool:
    """
    Return True if d is an open business day for the given location.
    DB overrides take precedence over the hardcoded baseline.
    """
    overrides = _load_db_overrides(location_id)

    # DB holiday closure always wins
    if d in overrides["holiday_closure"]:
        return False

    # DB special open Sunday always wins
    if d in overrides["special_open_sunday"]:
        return True

    # Hardcoded holiday closures (shared)
    if d in HOLIDAY_CLOSURES:
        return False

    # KAL special open Sundays
    if location_id == LOCATION_KAL and d in KAL_OPEN_SUNDAYS:
        return True

    # Baseline weekday check
    return d.weekday() in LOCATION_OPEN_WEEKDAYS.get(location_id, set())


def get_reporting_window(run_date: date, location_id: str = LOCATION_KAL):
    """
    Return (start_date, end_date) for the reporting window ending on run_date.

    start_date: the last open business day before run_date
    end_date:   run_date itself

    The caller is responsible for applying the correct open/close times:
        start: LOCATION_OPEN_TIME[location_id] on start_date
        end:   LOCATION_CLOSE_TIME[location_id] on run_date
    """
    d = run_date - timedelta(days=1)
    while not is_business_day(d, location_id):
        d -= timedelta(days=1)
    return d, run_date


def get_open_time(location_id: str = LOCATION_KAL) -> tuple[int, int]:
    """Return (hour, minute) for store open time in ET."""
    return LOCATION_OPEN_TIME.get(location_id, (10, 0))


def get_close_time(location_id: str = LOCATION_KAL) -> tuple[int, int]:
    """Return (hour, minute) for report window close time in ET (open time - 1 min next day)."""
    return LOCATION_CLOSE_TIME.get(location_id, (9, 59))