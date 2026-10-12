import unittest
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from modules.animation_player import (
    Animation,
    AnimationContext,
    AnimationRequest,
    can_start,
    cap_fill_channels,
    fill_panel,
    play_animation,
)
from tests.fakes import FakeCanvas, FakeMatrix

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
CONTEXT = AnimationContext(font_5x7=None, width=64, height=32)


class CanStartTest(unittest.TestCase):
    def test_starts_when_no_arrival_is_displayed(self):
        self.assertTrue(can_start(NOW, None, 10, 5, None))

    def test_must_finish_before_the_pulse_ahead_of_the_next_departure(self):
        arrival = NOW + timedelta(seconds=20)
        self.assertTrue(can_start(NOW, arrival, 14.9, 5, None))
        # ending exactly as the pulse begins is too late, the pulse needs the whole window
        self.assertFalse(can_start(NOW, arrival, 15, 5, None))

    def test_waits_out_the_gap_after_the_last_animation(self):
        self.assertFalse(can_start(NOW, None, 1, 5, NOW - timedelta(seconds=0.2)))
        self.assertTrue(can_start(NOW, None, 1, 5, NOW - timedelta(seconds=0.5)))

    def test_cannot_start_once_the_next_arrival_has_passed(self):
        self.assertFalse(can_start(NOW, NOW - timedelta(seconds=1), 1, 5, None))


class CapFillChannelsTest(unittest.TestCase):
    def test_caps_the_brightest_channel_keeping_the_hue(self):
        self.assertEqual(cap_fill_channels((255, 128, 0)), (60, 30, 0))

    def test_caps_full_blue_which_looks_dim_but_draws_full_current(self):
        self.assertEqual(cap_fill_channels((0, 0, 255)), (0, 0, 60))

    def test_leaves_dim_colors_unchanged(self):
        self.assertEqual(cap_fill_channels((40, 20, 60)), (40, 20, 60))

    def test_fill_panel_fills_through_the_guard(self):
        canvas = FakeCanvas()
        fill_panel(canvas, (0, 0, 255))
        self.assertEqual(canvas.fills, [(0, 0, 60)])


class _Params(BaseModel):
    color: tuple[int, int, int] = (255, 255, 255)


class _FakeClock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _request(draw_frame, duration_seconds: float = 1.0):
    animation = Animation("test", _Params, lambda params: duration_seconds, draw_frame)
    return AnimationRequest(animation, _Params(), duration_seconds, "test")


class PlayAnimationTest(unittest.TestCase):
    def test_draws_cleared_frames_until_the_duration(self):
        clock = _FakeClock()
        matrix = FakeMatrix()
        elapsed_seen = []

        def draw_frame(canvas, elapsed_seconds, params, context):
            elapsed_seen.append(elapsed_seconds)
            canvas.SetPixel(int(elapsed_seconds * 10), 0, 255, 0, 0)

        play_animation(matrix, FakeCanvas(), _request(draw_frame), CONTEXT, clock=clock, wait=clock.sleep)
        # about 30 frames a second, the last drawn within a frame of the end
        self.assertEqual(len(matrix.frames), len(elapsed_seen))
        self.assertLess(max(elapsed_seen), 1.0)
        self.assertGreater(max(elapsed_seen), 1.0 - 2 / 30)
        # each frame starts from a cleared canvas, so only that frame's pixel is lit
        self.assertTrue(all(len(frame) == 1 for frame in matrix.frames))

    def test_an_exception_ends_the_animation_and_returns_the_canvas(self):
        clock = _FakeClock()
        canvas = FakeCanvas()

        def draw_frame(canvas, elapsed_seconds, params, context):
            raise RuntimeError("broken animation")

        with self.assertLogs("modules.animation_player", "ERROR"):
            returned = play_animation(FakeMatrix(), canvas, _request(draw_frame), CONTEXT, clock=clock, wait=clock.sleep)
        self.assertIs(returned, canvas)


if __name__ == "__main__":
    unittest.main()
