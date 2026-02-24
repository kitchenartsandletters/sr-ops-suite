from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict

def run_daily_sales_report(
    start_et: datetime,
    end_et: datetime,
    *,
    write_csv: bool = True,
    write_pdf: bool = True,
    send_email: bool = True,
) -> Dict:
    """
    Returns structured result metadata.
    Does NOT depend on argparse.
    """