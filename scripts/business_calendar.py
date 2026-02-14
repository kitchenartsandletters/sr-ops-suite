"""
Business Calendar Utilities for sr-ops-suite

This module defines the business-day calendar for Kitchen Arts & Letters.

IMPORTANT:
- This module returns ONLY date boundaries (no times).
- Time-of-day logic (10:00 AM start → 9:59:59 AM end) is applied in daily_sales_report.py.
- A *reporting window* always begins on the last open business day before today and ends yesterday.
- If the store was closed for multiple consecutive days, those closed days are included in the window.

Examples of reporting windows (date boundaries only):
    • Fri after July 4 closure → covers Jul 3–Jul 4
    • Mon after weekend → covers Sat–Sun
    • Mon after two-day storm closure → covers Fri–Sun

This file intentionally handles only calendar-day logic.
daily_sales_report.py handles the 10:00 AM → 9:59:59 AM ET timestamp expansion.
"""

from datetime import date, timedelta
import logging

# ----------------------------
# 1. Static Calendar Data
# ----------------------------

# Regular open days: Mon–Sat
# Regular closed day: Sunday
# Exception: certain Sundays in December are OPEN
SPECIAL_OPEN_SUNDAYS_2025 = {
    date(2025, 12, 7),
    date(2025, 12, 14),
    date(2025, 12, 21),
}

# Annual holiday closures
HOLIDAY_CLOSURES_2025 = {
    # Saturday before Memorial Day = 5/24/2025
    date(2025, 5, 24),
    date(2025, 5, 26),   # Memorial Day
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 28),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    date(2025, 12, 26),  # Boxing Day
}

# ----------------------------
# 1b. Static Calendar Data — 2026
# ----------------------------

SPECIAL_OPEN_SUNDAYS_2026 = {
    date(2026, 12, 6),
    date(2026, 12, 13),
    date(2026, 12, 20),
}

HOLIDAY_CLOSURES_2026 = {
    date(2026, 1, 1),     # New Year's Day
    date(2026, 5, 23),    # Saturday before Memorial Day
    date(2026, 5, 24),    # Memorial Day Sunday closure
    date(2026, 7, 4),     # Independence Day
    date(2026, 9, 7),     # Labor Day
    date(2026, 11, 26),   # Thanksgiving
    date(2026, 12, 25),   # Christmas
    date(2026, 12, 26),   # Boxing Day
}

# ----------------------------
# 2. Business Day Logic
# ----------------------------

def is_business_day(d: date) -> bool:
    """
    Returns True if the store is open on date d.
    Business days: Monday–Saturday, unless closed for holiday.
    Sundays are closed EXCEPT special open Sundays.
    """

    year = d.year

    if year == 2025:
        holiday_set = HOLIDAY_CLOSURES_2025
        special_open_sundays = SPECIAL_OPEN_SUNDAYS_2025
    elif year == 2026:
        holiday_set = HOLIDAY_CLOSURES_2026
        special_open_sundays = SPECIAL_OPEN_SUNDAYS_2026
    else:
        # Safe fallback for future years
        holiday_set = set()
        special_open_sundays = set()

    # Holiday closures override everything
    if d in holiday_set:
        logging.debug(f"is_business_day({d}) -> False (holiday)")
        return False

    # Sunday logic
    if d.weekday() == 6:  # Sunday
        result = d in special_open_sundays
        logging.debug(f"is_business_day({d}) -> {result} (sunday logic)")
        return result

    # Normal business days: Mon (0) → Sat (5)
    result = d.weekday() in (0, 1, 2, 3, 4, 5)
    logging.debug(f"is_business_day({d}) -> {result} (weekday logic)")
    return result


def find_last_open_day(today: date) -> date:
    """
    Starting from the day before 'today', walk backward until reaching
    an open business day.
    """
    cursor = today - timedelta(days=1)
    logging.debug(f"find_last_open_day start: today={today}, cursor={cursor}")

    while not is_business_day(cursor):
        logging.debug(f"{cursor} is closed, stepping back")
        cursor -= timedelta(days=1)

    logging.debug(f"find_last_open_day resolved last open: {cursor}")
    return cursor


# ----------------------------
# 3. Reporting Window Logic
# ----------------------------

def get_reporting_window(today: date):
    """
    Returns (start_date, end_date) for the report.

    Start = last open business day
    End   = yesterday

    If yesterday is closed:
        include all closed days up to last open day.
    """
    logging.debug(f"get_reporting_window called for today={today}")
    yesterday = today - timedelta(days=1)

    # Find last open business day before 'today'
    last_open = find_last_open_day(today)

    # The window always starts on the last open business day…
    start_date = last_open

    # …and always ends yesterday (closed or not).
    end_date = yesterday

    logging.debug(f"Reporting window raw: {start_date} -> {end_date}")
    return start_date, end_date
