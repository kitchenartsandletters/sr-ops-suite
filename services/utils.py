import time
import logging
import requests

def _with_retry(fn, *args, max_attempts=3, retry_delay=10, **kwargs):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, requests.exceptions.HTTPError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            msg = str(e)
            if "Not Found" in msg or "404" in msg:
                raise  # Hard config error — don't retry
            last_exc = e
            if attempt < max_attempts:
                logging.warning(
                    f"[retry] Transient error (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logging.error(f"[retry] All {max_attempts} attempts failed: {e}")
    raise last_exc