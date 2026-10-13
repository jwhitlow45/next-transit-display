import os
import unittest
from unittest import mock

import modules.display_utils as display_utils
from animations.banner import BannerParams
from animations.convoy import ConvoyParams
from animations.flash import FlashParams
from modules.animation_player import AnimationContext, AnimationRequest, play_animation
from modules.animation_registry import ANIMATIONS
from modules.rgbmatrix_importer import get_rgb_matrix_imports
from tests.fakes import FakeCanvas, FakeMatrix

_, _, graphics = get_rgb_matrix_imports()

_FONT_5X7 = graphics.Font()
_FONT_5X7.LoadFont(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "5x7.bdf"))
CONTEXT = AnimationContext(font_5x7=_FONT_5X7, width=64, height=32)


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _play(name: str, params):
    animation = ANIMATIONS[name]
    request = AnimationRequest(animation, params, animation.duration_seconds(params), name)
    clock = _FakeClock()
    matrix = FakeMatrix()
    canvas = FakeCanvas()
    play_animation(matrix, canvas, request, CONTEXT, clock=clock, wait=clock.sleep)
    return matrix.frames, canvas


class PowerGuardTest(unittest.TestCase):
    def test_no_animation_fills_the_panel_around_the_power_guard(self):
        # fill_panel is the only way through the channel cap, so a direct Fill would light the panel past it
        animations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "animations")
        for file_name in sorted(os.listdir(animations_dir)):
            if file_name.endswith(".py"):
                with self.subTest(file_name), open(os.path.join(animations_dir, file_name)) as source:
                    self.assertNotIn(".Fill(", source.read())


class ConvoyTest(unittest.TestCase):
    def test_drives_through_the_middle_of_a_blank_panel(self):
        frames, _ = _play("convoy", ConvoyParams(sprites=("CHICKEN_JOCKEY", "PIG", "COW", "CREEPER")))
        lit_rows = {y for frame in frames for _, y in frame}
        # 7 pixel tall sprites centered on a 32 pixel panel
        self.assertEqual(lit_rows, set(range(12, 19)))
        # blank while the convoy waits off screen, then on screen mid-pass
        self.assertEqual(frames[0], {})
        self.assertTrue(frames[len(frames) // 2])

    def test_lasts_the_departure_animation_timing(self):
        self.assertEqual(ANIMATIONS["convoy"].duration_seconds(ConvoyParams(sprites=("PIG",))), 3.0)

    def test_drives_right_to_left_from_the_right_edge(self):
        frames, _ = _play("convoy", ConvoyParams(sprites=("PIG",), direction="L"))
        first_lit = next(frame for frame in frames if frame)
        self.assertGreater(min(x for x, _ in first_lit), 50)


class FlashTest(unittest.TestCase):
    def test_steps_through_each_color_through_the_power_guard(self):
        params = FlashParams(colors=((255, 0, 0), (0, 0, 255)), step_ms=500, repeats=2)
        _, canvas = _play("flash", params)
        distinct_fills = [fill for idx, fill in enumerate(canvas.fills) if idx == 0 or fill != canvas.fills[idx - 1]]
        self.assertEqual(distinct_fills, [(60, 0, 0), (0, 0, 60), (60, 0, 0), (0, 0, 60)])

    def test_duration_is_steps_times_repeats(self):
        params = FlashParams(colors=((1, 2, 3),) * 3, step_ms=600, repeats=2)
        self.assertAlmostEqual(ANIMATIONS["flash"].duration_seconds(params), 3.6)

    def test_colors_take_the_luminance_cap_before_the_power_guard(self):
        with mock.patch.object(display_utils, "COLOR_LUMINANCE_CAP", 20):
            _, canvas = _play("flash", FlashParams(colors=((255, 255, 255),)))
        self.assertEqual(set(canvas.fills), {(20, 20, 20)})


class BannerTest(unittest.TestCase):
    def test_scrolls_in_from_the_right_and_off_to_the_left(self):
        frames, _ = _play("banner", BannerParams(text="WARDEN"))
        self.assertEqual(frames[0], {})
        self.assertEqual(frames[-1], {})

    def test_text_sits_where_30_pixels_a_second_puts_it(self):
        params = BannerParams(text="WARDEN")
        white = graphics.Color(255, 255, 255)
        for elapsed_seconds in (0.5, 1.0, 2.0, 3.0):
            with self.subTest(elapsed_seconds):
                canvas = FakeCanvas()
                ANIMATIONS["banner"].draw_frame(canvas, elapsed_seconds, params, CONTEXT)
                expected = FakeCanvas()
                graphics.DrawText(expected, _FONT_5X7, 64 - int(elapsed_seconds * 30), 18, white, "WARDEN")
                self.assertTrue(canvas.pixels)
                self.assertEqual(canvas.pixels, expected.pixels)

    def test_draws_in_the_5x7_font_centered_on_the_panel(self):
        frames, _ = _play("banner", BannerParams(text="THE END"))
        lit_rows = {y for frame in frames for _, y in frame}
        self.assertTrue(lit_rows)
        self.assertTrue(lit_rows <= set(range(12, 20)))

    def test_duration_scrolls_the_whole_text_at_30_pixels_a_second(self):
        self.assertAlmostEqual(ANIMATIONS["banner"].duration_seconds(BannerParams(text="x" * 10)), (64 + 50) / 30)

    def test_color_takes_the_luminance_cap(self):
        with mock.patch.object(display_utils, "COLOR_LUMINANCE_CAP", 100):
            frames, _ = _play("banner", BannerParams(text="HI", color=(255, 255, 255)))
        self.assertEqual({rgb for frame in frames for rgb in frame.values()}, {(100, 100, 100)})


if __name__ == "__main__":
    unittest.main()
