# services/utils.py
import time
import logging

def _with_retry(fn, *args, max_attempts=3, retry_delay=10, **kwargs):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except RuntimeError as e:
            msg = str(e)
            if "Not Found" in msg or "404" in msg:
                raise
            last_exc = e
            if attempt < max_attempts:
                logging.warning(
                    f"[service] Transient Shopify error (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logging.error(f"[service] All {max_attempts} attempts failed: {e}")
    raise last_exc