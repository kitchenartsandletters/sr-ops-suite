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
# 2. Business Day Logic
# ----------------------------

def is_business_day(d: date) -> bool:
    """
    Returns True if the store is open on date d.
    Business days: Monday–Saturday, unless closed for holiday.
    Sundays are closed EXCEPT special open Sundays.
    """

    # Holiday closures override everything
    if d in HOLIDAY_CLOSURES_2025:
        result = False
        logging.debug(f"is_business_day({d}) -> {result}")
        return result

    # Special open Sundays
    if d.weekday() == 6:  # Sunday
        result = d in SPECIAL_OPEN_SUNDAYS_2025
        logging.debug(f"is_business_day({d}) -> {result}")
        return result

    # Normal business days: Mon (0) → Sat (5)
    result = d.weekday() in (0, 1, 2, 3, 4, 5)
    logging.debug(f"is_business_day({d}) -> {result}")
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
