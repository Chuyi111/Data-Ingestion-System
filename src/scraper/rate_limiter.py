"""
Rate limiting utilities for Google Play Review Scraper.

Implements configurable delays with random jitter to avoid detection
and respect rate limits.
"""

import random
import time
from typing import Optional

from src.config.settings import MIN_DELAY, MAX_DELAY, DEFAULT_DELAY


class RateLimiter:
    """
    Rate limiter with configurable delays and random jitter.

    Helps avoid detection by adding randomized delays between requests.
    """

    def __init__(
        self,
        min_delay: float = MIN_DELAY,
        max_delay: float = MAX_DELAY,
        default_delay: float = DEFAULT_DELAY
    ):
        """
        Initialize rate limiter.

        Args:
            min_delay: Minimum delay between requests (seconds)
            max_delay: Maximum delay between requests (seconds)
            default_delay: Default delay when not using random jitter
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.default_delay = default_delay
        self._last_request_time: Optional[float] = None

    def wait(self, use_jitter: bool = True):
        """
        Wait for the appropriate delay before next request.

        Args:
            use_jitter: If True, use random delay within range;
                       otherwise use default_delay
        """
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            delay = self._calculate_delay(use_jitter)

            # Only wait if not enough time has passed
            if elapsed < delay:
                time.sleep(delay - elapsed)

        self._last_request_time = time.time()

    def _calculate_delay(self, use_jitter: bool) -> float:
        """
        Calculate the delay to use.

        Args:
            use_jitter: Whether to use random jitter

        Returns:
            Delay in seconds
        """
        if use_jitter:
            return random.uniform(self.min_delay, self.max_delay)
        return self.default_delay

    def reset(self):
        """Reset the rate limiter state."""
        self._last_request_time = None


class ExponentialBackoff:
    """
    Exponential backoff for retry logic.

    Increases delay exponentially on each retry to handle temporary failures.
    """

    def __init__(
        self,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        max_retries: int = 3
    ):
        """
        Initialize exponential backoff.

        Args:
            base_delay: Initial delay (seconds)
            max_delay: Maximum delay cap (seconds)
            max_retries: Maximum number of retry attempts
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self._attempt = 0

    def wait(self) -> bool:
        """
        Wait with exponential backoff.

        Returns:
            True if should retry, False if max retries exceeded
        """
        if self._attempt >= self.max_retries:
            return False

        delay = min(
            self.base_delay * (2 ** self._attempt),
            self.max_delay
        )
        # Add small random jitter (10%)
        delay += random.uniform(0, delay * 0.1)

        time.sleep(delay)
        self._attempt += 1
        return True

    def reset(self):
        """Reset retry counter."""
        self._attempt = 0

    @property
    def attempts(self) -> int:
        """Get current attempt count."""
        return self._attempt

    @property
    def can_retry(self) -> bool:
        """Check if more retries are available."""
        return self._attempt < self.max_retries
