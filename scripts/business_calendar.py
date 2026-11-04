"""
business_calendar.py

Business calendar logic for KAL sr-ops-suite.

SOURCE OF TRUTH: reports.business_calendar_overrides (per location_id).
Holidays, special open Sundays and one-off closures all live there, and the
admin dashboard's Business Calendar page reads and writes the same rows. There
is no hardcoded holiday list in code any more (removed 2026-11-04, after the
code list and the dashboard's own list had drifted apart). Add next year's
holidays in the dashboard before the year starts.

Locations:
    kal  — 1435 Lexington Ave, Mon–Sat, opens 10:00 AM ET
    nyfs — 111 Broadway, Tue–Sun, opens 12:00 PM ET (pop-up closed Sept 2026)

Override types:
    holiday_closure     — marks an otherwise-open day as closed
    special_open_sunday — marks a Sunday as open (KAL)
    open_override       — marks a day open that would otherwise be closed

If the overrides cannot be loaded and there is no last-known-good copy, this
module RAISES rather than guessing: a wrong calendar silently skips or adds a
report, while a raised error fails the job and emails an alert.

NOTE ON DATES: everything here is plain `date` arithmetic. The ET open/close
instants are built by the caller with ZoneInfo, which resolves EDT/EST per date,
so merged windows that cross a DST transition are correct (49h in fall, 47h in spring).
"""

import logging
import time
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
    LOCATION_KAL:  {0, 1, 2, 3, 4, 5},   # Mon–Sat
    LOCATION_NYFS: {1, 2, 3, 4, 5, 6},   # Tue–Sun
}

# ─── DB override cache ────────────────────────────────────────────────────────
# The report worker is a long-lived process. The previous cache was never
# invalidated, so a closure added in the dashboard after the worker started was
# ignored until the next deploy — and a failed load cached an EMPTY result forever.
# Now: entries expire after _CACHE_TTL_SECONDS; a failed load retries, then serves
# the last known-good data, and raises if there is none.

_CACHE_TTL_SECONDS = 300
_FAILED_RETRY_SECONDS = 60
_LOAD_ATTEMPTS = 3
_LOAD_RETRY_DELAY_SECONDS = 2
_db_overrides_cache: dict[str, tuple[float, dict]] = {}   # location_id -> (loaded_at_monotonic, data)


def _empty_overrides() -> dict:
    return {
        "holiday_closure":     set(),
        "special_open_sunday": set(),
        "open_override":       set(),
    }


def _load_db_overrides(location_id: str) -> dict:
    """
    Fetch calendar overrides from Supabase for a given location.
    Returns {
        "holiday_closure":     set[date],
        "special_open_sunday": set[date],
        "open_override":       set[date],
    }
    Cached for _CACHE_TTL_SECONDS. On failure: retries, then serves the last
    known-good data if there is any, otherwise raises.
    """
    now    = time.monotonic()
    cached = _db_overrides_cache.get(location_id)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    last_error = None
    for attempt in range(1, _LOAD_ATTEMPTS + 1):
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
            result = _empty_overrides()
            rows = resp.data or []
            for row in rows:
                d     = date.fromisoformat(row["date"])
                otype = row["override_type"]
                if otype in result:
                    result[otype].add(d)
            if not rows:
                logging.warning(
                    f"[calendar] No calendar overrides found for '{location_id}'. Every "
                    f"baseline weekday will be treated as open, including holidays."
                )
            _db_overrides_cache[location_id] = (time.monotonic(), result)
            return result
        except Exception as e:
            last_error = e
            logging.warning(
                f"[calendar] Failed to load DB overrides for {location_id} "
                f"(attempt {attempt}/{_LOAD_ATTEMPTS}): {e}"
            )
            if attempt < _LOAD_ATTEMPTS:
                time.sleep(_LOAD_RETRY_DELAY_SECONDS)

    if cached:
        # Serve stale-but-real data; retry sooner than a full TTL.
        _db_overrides_cache[location_id] = (now - _CACHE_TTL_SECONDS + _FAILED_RETRY_SECONDS, cached[1])
        logging.warning(f"[calendar] Serving last known-good overrides for {location_id}.")
        return cached[1]

    raise RuntimeError(
        f"Business calendar unavailable for '{location_id}': could not load overrides "
        f"from reports.business_calendar_overrides after {_LOAD_ATTEMPTS} attempts "
        f"({last_error}). Refusing to guess which days are holidays."
    )


def _clear_cache():
    """Clear the override cache (useful for testing)."""
    _db_overrides_cache.clear()


# ─── Core calendar logic ──────────────────────────────────────────────────────

def is_business_day(d: date, location_id: str = LOCATION_KAL) -> bool:
    """
    Return True if d is an open business day for the given location.
    Overrides come from the database; days without one use the location's weekdays.

    Priority order (first match wins):
    1. holiday_closure      -> closed
    2. open_override        -> open
    3. special_open_sunday  -> open
    4. Baseline weekday check for the location
    """
    overrides = _load_db_overrides(location_id)

    if d in overrides["holiday_closure"]:
        return False
    if d in overrides["open_override"]:
        return True
    if d in overrides["special_open_sunday"]:
        return True
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
