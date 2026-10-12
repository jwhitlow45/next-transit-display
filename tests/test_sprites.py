import unittest

from modules.sprites import (
    SPRITE_COLOR_LEGEND,
    SPRITES_BY_NAME,
    AnimationDirection,
    build_convoy,
    draw_convoy,
    validate_sprite,
)
from tests.fakes import FakeCanvas


class ValidateSpriteTest(unittest.TestCase):
    def test_every_registered_sprite_is_valid(self):
        for sprite_name, sprite in SPRITES_BY_NAME.items():
            with self.subTest(sprite_name):
                validate_sprite(sprite_name, sprite)

    def test_rejects_more_than_seven_rows(self):
        with self.assertRaisesRegex(ValueError, "TALL"):
            validate_sprite("TALL", ["R"] * 8)

    def test_rejects_ragged_rows(self):
        with self.assertRaisesRegex(ValueError, "RAGGED"):
            validate_sprite("RAGGED", ["RR", "R"])

    def test_rejects_characters_missing_from_the_legend(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN"):
            validate_sprite("UNKNOWN", ["R?"])


class BuildConvoyTest(unittest.TestCase):
    def test_leading_sprite_is_rightmost_driving_left_to_right(self):
        convoy = build_convoy(("BUS", "STREETCAR"), AnimationDirection.LEFT_TO_RIGHT)
        self.assertEqual(convoy.sprites[-1], tuple(SPRITES_BY_NAME["BUS"]))
        self.assertEqual(convoy.sprites[0], tuple(SPRITES_BY_NAME["STREETCAR"]))

    def test_leading_sprite_is_leftmost_and_mirrored_driving_right_to_left(self):
        convoy = build_convoy(("BUS", "STREETCAR"), AnimationDirection.RIGHT_TO_LEFT)
        self.assertEqual(convoy.sprites[0], tuple(row[::-1] for row in SPRITES_BY_NAME["BUS"]))

    def test_layout_spans_sprites_and_six_pixel_gaps(self):
        convoy = build_convoy(("BUS", "STREETCAR"), AnimationDirection.LEFT_TO_RIGHT)
        streetcar_width = len(SPRITES_BY_NAME["STREETCAR"][0])
        bus_width = len(SPRITES_BY_NAME["BUS"][0])
        self.assertEqual(convoy.x_offsets, (0, streetcar_width + 6))
        self.assertEqual(convoy.width, streetcar_width + 6 + bus_width)
        self.assertEqual(convoy.height, 7)

    def test_is_cached(self):
        self.assertIs(
            build_convoy(("BAT",), AnimationDirection.LEFT_TO_RIGHT),
            build_convoy(("BAT",), AnimationDirection.LEFT_TO_RIGHT),
        )


class DrawConvoyTest(unittest.TestCase):
    def test_sprites_rest_on_the_road_line(self):
        canvas = FakeCanvas()
        convoy = build_convoy(("BUS",), AnimationDirection.LEFT_TO_RIGHT)
        draw_convoy(canvas, convoy, 10, road_y_pos=20)
        # the bus's wheels are its bottom row, "..KK......KK..", one pixel above the road line
        self.assertEqual(canvas.pixels[(12, 19)], SPRITE_COLOR_LEGEND["K"])
        self.assertNotIn((12, 20), canvas.pixels)
        self.assertEqual(min(y for _, y in canvas.pixels), 13)

    def test_short_sprites_keep_their_transparent_rows(self):
        canvas = FakeCanvas()
        draw_convoy(canvas, build_convoy(("BAT",), AnimationDirection.LEFT_TO_RIGHT), 0, road_y_pos=20)
        # the bat's bottom three rows are empty, so it flies three pixels above the road
        self.assertEqual(max(y for _, y in canvas.pixels), 16)


if __name__ == "__main__":
    unittest.main()
