import unittest
from unittest import mock

import modules.departure_animation as departure_animation
from modules.departure_convoy import DepartureConvoy
from modules.sprites import AnimationDirection
from tests.fakes import FakeCanvas

_ROCKY = b'{"v": 1, "sprites": ["WATER_DROP", "ROCKY_ANGRY", "TUMBLEWEED", "CACTUS"]}'


class DepartureConvoyTest(unittest.TestCase):
    def test_starts_with_the_configured_convoy(self):
        self.assertEqual(DepartureConvoy(("BUS", "STREETCAR")).sprite_names(), ("BUS", "STREETCAR"))

    def test_a_published_convoy_swaps_in_and_an_empty_payload_clears_it(self):
        convoy = DepartureConvoy(("BUS",))
        with self.assertLogs("modules.departure_convoy", "INFO"):
            convoy.submit(_ROCKY)
        self.assertEqual(convoy.sprite_names(), ("WATER_DROP", "ROCKY_ANGRY", "TUMBLEWEED", "CACTUS"))
        # an empty retained message is how MQTT deletes one, and the broker forwards it to subscribers
        with self.assertLogs("modules.departure_convoy", "INFO"):
            convoy.submit(b"")
        self.assertEqual(convoy.sprite_names(), ("BUS",))

    def test_clearing_with_nothing_swapped_logs_nothing(self):
        convoy = DepartureConvoy(("BUS",))
        with self.assertNoLogs("modules.departure_convoy", "INFO"):
            convoy.submit(b"")

    def test_resending_the_same_convoy_logs_once(self):
        convoy = DepartureConvoy(("BUS",))
        with self.assertLogs("modules.departure_convoy", "INFO") as logs:
            convoy.submit(_ROCKY)
            convoy.submit(_ROCKY)
        self.assertEqual(len(logs.output), 1)

    def test_a_bad_request_keeps_the_current_convoy(self):
        bad_payloads = {
            "unknown sprite": b'{"v": 1, "sprites": ["ROCKY_ANGRY", "DINOSAUR"]}',
            "no sprites": b'{"v": 1, "sprites": []}',
            "too many sprites": b'{"v": 1, "sprites": ["PIG", "PIG", "PIG", "PIG", "PIG", "PIG", "PIG"]}',
            "a version 2 request": b'{"v": 2, "sprites": ["PIG"]}',
            "an unknown field": b'{"v": 1, "sprites": ["PIG"], "direction": "L"}',
            "not JSON": b"\xff\xfe",
            "over the size cap": b'{"v": 1, "sprites": ["PIG"]}' + b" " * 5000,
        }
        for reason, payload in bad_payloads.items():
            with self.subTest(reason):
                convoy = DepartureConvoy(("BUS",))
                convoy.submit(_ROCKY)
                with self.assertLogs("modules.departure_convoy", "WARNING"):
                    convoy.submit(payload)
                self.assertEqual(convoy.sprite_names(), ("WATER_DROP", "ROCKY_ANGRY", "TUMBLEWEED", "CACTUS"))

    def test_rejections_are_logged_at_most_once_a_minute(self):
        clock = mock.Mock(return_value=0.0)
        convoy = DepartureConvoy(("BUS",), clock=clock)
        with self.assertLogs("modules.departure_convoy", "WARNING") as logs:
            for _ in range(5):
                convoy.submit(b"not json")
        self.assertEqual(len(logs.output), 1)


class ConvoyPlayersTest(unittest.TestCase):
    def _drive(self, play, **kwargs):
        frames = []
        with mock.patch.object(
            departure_animation, "_play_frames", lambda matrix, canvas, draw_frame: frames.append(draw_frame)
        ):
            play(None, FakeCanvas(), **kwargs)
        return frames[0]

    def test_the_loading_pass_drives_the_sprites_it_is_given_or_the_configured_ones(self):
        with mock.patch.object(departure_animation, "draw_convoy_pass_frame") as draw:
            self._drive(
                departure_animation.play_loading_animation,
                display_width=64,
                display_height=32,
                sprite_names=("ROCKY_ANGRY",),
            )(FakeCanvas(), 1.0)
            self._drive(departure_animation.play_loading_animation, display_width=64, display_height=32)(
                FakeCanvas(), 1.0
            )
        self.assertEqual(draw.call_args_list[0].args[1], ("ROCKY_ANGRY",))
        self.assertEqual(draw.call_args_list[1].args[1], departure_animation._DEPARTURE_SPRITE_NAMES)

    def test_departures_drive_the_sprites_they_are_given(self):
        row = departure_animation.DepartureAnimationRow(row_y_pos=8, direction=AnimationDirection.LEFT_TO_RIGHT)
        with mock.patch.object(departure_animation, "build_convoy", wraps=departure_animation.build_convoy) as build:
            draw_frame = self._drive(
                departure_animation.play_departure_animation,
                display_width=64,
                animation_row_list=[row],
                row_height=8,
                draw_background=lambda canvas: None,
                draw_segments=lambda canvas, segments, brightness_percent, x_offset: None,
                sprite_names=("WATER_DROP", "ROCKY_ANGRY"),
            )
            draw_frame(FakeCanvas(), 1.5)  # mid-travel, after the row has faded out
        build.assert_called_with(("WATER_DROP", "ROCKY_ANGRY"), AnimationDirection.LEFT_TO_RIGHT)


if __name__ == "__main__":
    unittest.main()
