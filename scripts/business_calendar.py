"""
Business Calendar Utilities for sr-ops-suite

This module defines the business-day calendar for Kitchen Arts & Letters.

IMPORTANT:
- This module returns ONLY date boundaries (no times).
- Time-of-day logic (10:00 AM start → 9:59:59 AM end) is applied in daily_sales_service.py.
- A *reporting window* always begins on the last open business day before today and ends yesterday.
- If the store was closed for multiple consecutive days, those closed days are included in the window.

DB overrides (reports.business_calendar_overrides) always win over the hardcoded
baseline sets when a row exists for a given date. Hardcoded data is used as the
fallback for years with no DB rows.
"""

from datetime import date, timedelta
import logging
from typing import Optional

try:
    from services.supabase_client import supabase
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    supabase = None

# ----------------------------
# 1. Hardcoded Baseline Data
# ----------------------------

SPECIAL_OPEN_SUNDAYS_2025 = {
    date(2025, 12, 7),
    date(2025, 12, 14),
    date(2025, 12, 21),
}

HOLIDAY_CLOSURES_2025 = {
    date(2025, 5, 24),
    date(2025, 5, 26),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 28),
    date(2025, 12, 25),
    date(2025, 12, 26),
}

SPECIAL_OPEN_SUNDAYS_2026 = {
    date(2026, 12, 6),
    date(2026, 12, 13),
    date(2026, 12, 20),
}

HOLIDAY_CLOSURES_2026 = {
    date(2026, 1, 1),
    date(2026, 5, 23),
    date(2026, 5, 24),
    date(2026, 7, 4),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2026, 12, 26),
}


# ----------------------------
# 2. DB Override Loader
# ----------------------------

def get_calendar_overrides(year: int) -> tuple[set[date], set[date]]:
    """
    Fetch calendar overrides from Supabase for the given year.
    Returns (holiday_closures, special_open_sundays) as sets of date objects.

    DB rows always win over hardcoded baseline. If Supabase is unavailable,
    falls back to hardcoded sets silently.
    """
    if not _SUPABASE_AVAILABLE or supabase is None:
        return _baseline_for_year(year)

    try:
        resp = (
            supabase
            .schema("reports")
            .table("business_calendar_overrides")
            .select("date, override_type")
            .eq("year", year)
            .execute()
        )
        rows = resp.data or []
    except Exception as e:
        logging.warning(f"[calendar] Failed to fetch overrides for {year}: {e}. Using baseline.")
        return _baseline_for_year(year)

    if not rows:
        # No DB rows for this year — use hardcoded baseline as-is
        return _baseline_for_year(year)

    # Start from baseline, then apply DB overrides (DB always wins)
    baseline_holidays, baseline_specials = _baseline_for_year(year)
    holidays = set(baseline_holidays)
    specials = set(baseline_specials)

    for row in rows:
        d = date.fromisoformat(row["date"])
        if row["override_type"] == "holiday_closure":
            holidays.add(d)
            specials.discard(d)
        elif row["override_type"] == "special_open_sunday":
            specials.add(d)
            holidays.discard(d)

    return holidays, specials


def _baseline_for_year(year: int) -> tuple[set[date], set[date]]:
    """Return hardcoded baseline sets for the given year."""
    if year == 2025:
        return set(HOLIDAY_CLOSURES_2025), set(SPECIAL_OPEN_SUNDAYS_2025)
    if year == 2026:
        return set(HOLIDAY_CLOSURES_2026), set(SPECIAL_OPEN_SUNDAYS_2026)
    # Future years: base schedule only (Mon–Sat open, Sun closed)
    return set(), set()


# ----------------------------
# 3. Business Day Logic
# ----------------------------

def is_business_day(d: date, _holidays: Optional[set] = None, _specials: Optional[set] = None) -> bool:
    """
    Returns True if the store is open on date d.

    If _holidays/_specials are provided (pre-fetched), uses those directly.
    Otherwise fetches from DB (with hardcoded fallback) for d.year.
    """
    if _holidays is None or _specials is None:
        _holidays, _specials = get_calendar_overrides(d.year)

    if d in _holidays:
        logging.debug(f"is_business_day({d}) -> False (holiday/closure)")
        return False

    if d.weekday() == 6:  # Sunday
        result = d in _specials
        logging.debug(f"is_business_day({d}) -> {result} (sunday logic)")
        return result

    result = d.weekday() in (0, 1, 2, 3, 4, 5)
    logging.debug(f"is_business_day({d}) -> {result} (weekday logic)")
    return result


def find_last_open_day(today: date, _holidays: Optional[set] = None, _specials: Optional[set] = None) -> date:
    """
    Starting from the day before 'today', walk backward until reaching
    an open business day.

    Pass pre-fetched _holidays/_specials to avoid repeated DB calls.
    """
    cursor = today - timedelta(days=1)
    logging.debug(f"find_last_open_day start: today={today}, cursor={cursor}")

    while True:
        # Fetch overrides for cursor's year if year boundary crossed
        h = _holidays
        s = _specials
        if h is None or s is None:
            h, s = get_calendar_overrides(cursor.year)
        if is_business_day(cursor, h, s):
            break
        logging.debug(f"{cursor} is closed, stepping back")
        cursor -= timedelta(days=1)

    logging.debug(f"find_last_open_day resolved: {cursor}")
    return cursor


# ----------------------------
# 4. Reporting Window Logic
# ----------------------------

def get_reporting_window(today: date) -> tuple[date, date]:
    """
    Returns (start_date, end_date) for the report.

    Fetches DB overrides once for today.year (and yesterday.year if crossing
    a year boundary) to avoid repeated Supabase calls per iteration.

    Start = last open business day
    End   = yesterday
    """
    logging.debug(f"get_reporting_window called for today={today}")
    yesterday = today - timedelta(days=1)

    # Pre-fetch overrides for the relevant year(s)
    holidays, specials = get_calendar_overrides(today.year)
    if yesterday.year != today.year:
        h2, s2 = get_calendar_overrides(yesterday.year)
        holidays = holidays | h2
        specials = specials | s2

    last_open  = find_last_open_day(today, holidays, specials)
    start_date = last_open
    end_date   = yesterday

    logging.debug(f"Reporting window: {start_date} -> {end_date}")
    return start_date, end_date