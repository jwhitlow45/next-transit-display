import threading
import time
import unittest

from pydantic import BaseModel

from modules.animation_player import Animation, AnimationRequest
from modules.animation_queue import AnimationQueue

# these waits time out after 5 s, so returning within 4 s proves an early wake while leaving room for a
# loaded Pi or CI host
_WOKE_EARLY_SECONDS = 4


class _Params(BaseModel):
    value: int = 0


def _request(name: str = "test", value: int = 0, duration_seconds: float = 1.0):
    animation = Animation(name, _Params, lambda params: duration_seconds, lambda *args: None)
    params = _Params(value=value)
    return AnimationRequest(animation, params, duration_seconds, f"{name}:{params.model_dump_json()}")


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _always(duration_seconds):
    return True


class PutTest(unittest.TestCase):
    def test_bumps_the_generation(self):
        queue = AnimationQueue()
        self.assertTrue(queue.put(_request()))
        self.assertEqual(queue.generation, 1)

    def test_coalesces_an_equal_waiting_request_without_bumping(self):
        queue = AnimationQueue()
        queue.put(_request(value=1))
        self.assertFalse(queue.put(_request(value=1)))
        self.assertEqual(queue.generation, 1)
        self.assertTrue(queue.put(_request(value=2)))

    def test_a_repeat_of_an_expired_request_is_queued_not_coalesced(self):
        clock = _FakeClock()
        queue = AnimationQueue(ttl_seconds=15, clock=clock)
        queue.put(_request(value=1))
        clock.now += 20
        self.assertTrue(queue.put(_request(value=1)))
        self.assertEqual(queue.pop_if_startable(_always).params.value, 1)

    def test_drops_the_oldest_when_full(self):
        queue = AnimationQueue(max_requests=3)
        for value in range(4):
            queue.put(_request(value=value))
        popped = [queue.pop_if_startable(_always).params.value for _ in range(3)]
        self.assertEqual(popped, [1, 2, 3])
        self.assertIsNone(queue.pop_if_startable(_always))


    def test_a_flood_of_drops_logs_one_line_a_minute(self):
        clock = _FakeClock()
        queue = AnimationQueue(max_requests=3, clock=clock)
        with self.assertLogs("modules.animation_queue", "INFO") as logs:
            for value in range(10):
                queue.put(_request(value=value))
        self.assertEqual(len(logs.output), 1)


class PopIfStartableTest(unittest.TestCase):
    def test_pops_in_arrival_order(self):
        queue = AnimationQueue()
        queue.put(_request(value=1))
        queue.put(_request(value=2))
        self.assertEqual(queue.pop_if_startable(_always).params.value, 1)
        self.assertEqual(queue.pop_if_startable(_always).params.value, 2)

    def test_head_that_cannot_start_holds_the_queue_in_order(self):
        queue = AnimationQueue()
        queue.put(_request(value=1, duration_seconds=10))
        queue.put(_request(value=2, duration_seconds=1))
        self.assertIsNone(queue.pop_if_startable(lambda duration_seconds: duration_seconds < 5))
        self.assertTrue(queue.has_waiting())
        self.assertEqual(queue.pop_if_startable(_always).params.value, 1)

    def test_passes_the_head_duration_to_the_start_rule(self):
        queue = AnimationQueue()
        queue.put(_request(duration_seconds=2.5))
        durations = []
        queue.pop_if_startable(lambda duration_seconds: durations.append(duration_seconds) or False)
        self.assertEqual(durations, [2.5])

    def test_drops_requests_older_than_the_ttl(self):
        clock = _FakeClock()
        queue = AnimationQueue(ttl_seconds=15, clock=clock)
        queue.put(_request(value=1))
        clock.now += 10
        queue.put(_request(value=2))
        clock.now += 6
        self.assertEqual(queue.pop_if_startable(_always).params.value, 2)
        self.assertFalse(queue.has_waiting())


class WaitForNewTest(unittest.TestCase):
    def test_returns_at_once_for_a_request_submitted_since_the_last_pop(self):
        queue = AnimationQueue()
        queue.pop_if_startable(_always)
        queue.put(_request())
        start = time.monotonic()
        queue.wait_for_new(5)
        self.assertLess(time.monotonic() - start, _WOKE_EARLY_SECONDS)

    def test_waiting_requests_alone_do_not_wake_it(self):
        queue = AnimationQueue()
        queue.put(_request(duration_seconds=10))
        # the display thread saw the request and left it waiting, as it does when a departure is due
        self.assertIsNone(queue.pop_if_startable(lambda duration_seconds: False))
        start = time.monotonic()
        queue.wait_for_new(0.1)
        self.assertGreaterEqual(time.monotonic() - start, 0.1)

    def test_wakes_when_another_thread_submits(self):
        queue = AnimationQueue()
        timer = threading.Timer(0.05, lambda: queue.put(_request()))
        timer.start()
        start = time.monotonic()
        queue.wait_for_new(5)
        timer.join()
        self.assertLess(time.monotonic() - start, _WOKE_EARLY_SECONDS)

    def test_one_submission_wakes_one_wait(self):
        queue = AnimationQueue()
        queue.put(_request())
        queue.wait_for_new(5)
        start = time.monotonic()
        queue.wait_for_new(0.1)
        self.assertGreaterEqual(time.monotonic() - start, 0.1)


if __name__ == "__main__":
    unittest.main()
