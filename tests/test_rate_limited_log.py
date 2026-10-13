import logging
import unittest

from modules.rate_limited_log import RateLimitedLog

logger = logging.getLogger("test_rate_limited_log")


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RateLimitedLogTest(unittest.TestCase):
    def test_logs_the_first_event_at_once(self):
        with self.assertLogs(logger, "WARNING") as logs:
            RateLimitedLog(logger, logging.WARNING, clock=_FakeClock()).record("first")
        self.assertEqual(logs.output, ["WARNING:test_rate_limited_log:first (1 since the last report)"])

    def test_counts_the_events_held_back_within_the_interval(self):
        clock = _FakeClock()
        log = RateLimitedLog(logger, logging.WARNING, interval_seconds=60, clock=clock)
        with self.assertLogs(logger, "WARNING") as logs:
            for _ in range(4):
                log.record("event")
            clock.now += 59
            log.record("event")
            clock.now += 1
            log.record("latest")
        self.assertEqual(len(logs.output), 2)
        self.assertTrue(logs.output[1].endswith("latest (5 since the last report)"))


if __name__ == "__main__":
    unittest.main()
