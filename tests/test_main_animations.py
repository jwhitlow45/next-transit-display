import json
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
from modules.animation_queue import AnimationQueue
from modules.animation_registry import parse_request

_FLASH = json.dumps({"v": 1, "animation": "flash", "params": {"colors": [[255, 255, 255]]}}).encode()


def _queue_with_flash():
    queue = AnimationQueue()
    queue.put(parse_request(_FLASH))
    return queue


class PlayStartableAnimationTest(unittest.TestCase):
    def test_does_nothing_with_the_listener_off(self):
        with mock.patch.object(main, "animation_queue", None), mock.patch.object(main, "play_animation") as play:
            canvas, last_end, played = main.play_startable_animation(None, "canvas", None, None, None)
        play.assert_not_called()
        self.assertEqual((canvas, last_end, played), ("canvas", None, False))

    def test_plays_when_the_next_departure_is_far_off(self):
        queue = _queue_with_flash()
        next_arrival = datetime.now(timezone.utc) + timedelta(minutes=5)
        with mock.patch.object(main, "animation_queue", queue), mock.patch.object(main, "play_animation") as play:
            play.return_value = "swapped canvas"
            canvas, last_end, played = main.play_startable_animation(None, "canvas", None, next_arrival, None)
        play.assert_called_once()
        self.assertTrue(played)
        self.assertEqual(canvas, "swapped canvas")
        self.assertIsNotNone(last_end)
        self.assertFalse(queue.has_waiting())

    def test_holds_the_request_when_a_departure_is_due_first(self):
        queue = _queue_with_flash()
        # the pulse ahead of this arrival begins before a 0.7 s flash could finish
        next_arrival = datetime.now(timezone.utc) + timedelta(seconds=5.5)
        with mock.patch.object(main, "animation_queue", queue), mock.patch.object(main, "play_animation") as play:
            _, _, played = main.play_startable_animation(None, "canvas", None, next_arrival, None)
        play.assert_not_called()
        self.assertFalse(played)
        self.assertTrue(queue.has_waiting())


class SleepUntilNextFrameTest(unittest.TestCase):
    def test_a_new_request_ends_the_sleep_early(self):
        queue = AnimationQueue()
        timer = threading.Timer(0.05, lambda: queue.put(parse_request(_FLASH)))
        with mock.patch.object(main, "animation_queue", queue):
            timer.start()
            start = time.monotonic()
            main.sleep_until_next_frame(None, None)
            timer.join()
        self.assertLess(time.monotonic() - start, 1)

    def test_a_held_request_does_not_end_the_sleep(self):
        queue = _queue_with_flash()
        queue.pop_if_startable(lambda duration_seconds: False)  # seen and held, as for a departure
        next_arrival = datetime.now(timezone.utc) + timedelta(seconds=5.3)
        with mock.patch.object(main, "animation_queue", queue):
            start = time.monotonic()
            main.sleep_until_next_frame(next_arrival, None)
        # sleeps until the pulse window opens 0.3 s from now, not straight back to a busy loop
        self.assertGreater(time.monotonic() - start, 0.2)

    def test_wakes_when_the_gap_after_the_last_animation_ends(self):
        queue = _queue_with_flash()
        queue.pop_if_startable(lambda duration_seconds: False)
        last_end = time.monotonic() - 0.3
        with mock.patch.object(main, "animation_queue", queue):
            start = time.monotonic()
            main.sleep_until_next_frame(None, last_end)
        self.assertLess(time.monotonic() - start, 1)


class StartAnimationListenerTest(unittest.TestCase):
    def test_loads_the_5x7_font_before_connecting(self):
        repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        test_dir = os.getcwd()
        os.chdir(repo_dir)  # the font path is relative to the display's working directory
        try:
            with mock.patch("modules.animation_mqtt.AnimationListener") as listener_class:
                queue, context = main.start_animation_listener()
        finally:
            os.chdir(test_dir)
        listener_class.return_value.start.assert_called_once()
        self.assertIsInstance(queue, AnimationQueue)
        self.assertEqual((context.width, context.height), (64, 32))
        self.assertIsNotNone(context.font_5x7)

    def test_a_missing_font_fails_at_startup_before_connecting(self):
        # the test runner's scratch directory has no fonts/ folder
        with mock.patch("modules.animation_mqtt.AnimationListener") as listener_class:
            with self.assertRaises(Exception):
                main.start_animation_listener()
        listener_class.return_value.start.assert_not_called()


class ListenerSettingsTest(unittest.TestCase):
    def test_enabling_the_listener_requires_broker_settings(self):
        # environment.py validates at import, so check it in a fresh interpreter
        environment = {**os.environ, "ENABLE_ANIMATION_LISTENER": "1", "ANIMATION_MQTT_HOST": "", "ANIMATION_MQTT_USERNAME": "", "ANIMATION_MQTT_PASSWORD": ""}
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import modules.environment"],
            env={**environment, "PYTHONPATH": os.pathsep.join(sys.path)},
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANIMATION_MQTT_HOST is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
