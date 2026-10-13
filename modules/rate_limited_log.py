"""Log lines limited to one per interval, for events a flood of MQTT messages could repeat many times a second

Each line carries the count of events since the last one, so nothing goes unreported, while a looping or broken
publisher can't fill the Pi's SD card. Kept free of modules.environment like the other animation modules.
"""

import logging
from time import monotonic
from typing import Callable


class RateLimitedLog:
    """Logs at most one line per interval, counting the events in between

    Not locked: each instance is used from one thread, or under its owner's lock
    """

    def __init__(self, logger: logging.Logger, level: int, interval_seconds: float = 60, clock: Callable[[], float] = monotonic):
        self._logger = logger
        self._level = level
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._last_logged_at: float | None = None
        self._unlogged_events = 0

    def record(self, latest: str):
        """Counts one event, logging it unless a line already went out within the interval"""
        self._unlogged_events += 1
        now = self._clock()
        if self._last_logged_at is not None and now - self._last_logged_at < self._interval_seconds:
            return
        self._logger.log(self._level, f"{latest} ({self._unlogged_events} since the last report)")
        self._last_logged_at = now
        self._unlogged_events = 0
