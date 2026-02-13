import functools
import logging
import time

logger = logging.getLogger(__name__)


def with_retry(max_retries: int = 3, base_delay: float = 1.0, exceptions: tuple = (Exception,)):
    """Decorator that retries a function with exponential backoff.

    Delays: base_delay * 2^attempt (e.g. 1s, 2s, 4s).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "%s attempt %d failed: %s. Retrying in %.1fs...",
                            func.__name__, attempt + 1, e, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__, max_retries + 1, e,
                        )
            raise last_exception

        return wrapper

    return decorator
