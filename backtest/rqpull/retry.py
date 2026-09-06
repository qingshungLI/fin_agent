from __future__ import annotations

import time

from .quota import QuotaExhausted


def call_with_retry(func, *args, **kwargs):
    delays = (2, 8, 32)
    for attempt in range(len(delays) + 1):
        try:
            return func(*args, **kwargs)
        except QuotaExhausted:
            raise
        except (PermissionError, ValueError, TypeError):
            raise
        except Exception:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])

