import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fakes import FakeCanvas
from google.transit import gtfs_realtime_pb2

import main
from models.DisplayInfo import DisplayInfoModel, StopVisitModel
from models.OpenData511 import TransitTripUpdatesResponse

_FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "5x7.bdf")
_NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)
_STOP = "13516"


def _font():
    font = main.graphics.Font()
    font.LoadFont(_FONT_PATH)
    return font


def _feed(*trips):
    """A trip updates feed of (route, [(stop_sequence, stop_id, arrival or None, departure or None)]) trips"""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(_NOW.timestamp())
    for trip_idx, (route_id, stop_time_updates) in enumerate(trips):
        entity = feed.entity.add()
        entity.id = str(trip_idx)
        entity.trip_update.trip.trip_id = str(trip_idx)
        entity.trip_update.trip.route_id = route_id
        for stop_sequence, stop_id, arrival, departure in stop_time_updates:
            stop_time_update = entity.trip_update.stop_time_update.add()
            stop_time_update.stop_sequence = stop_sequence
            stop_time_update.stop_id = stop_id
            if arrival is not None:
                stop_time_update.arrival.time = int(arrival.timestamp())
            if departure is not None:
                stop_time_update.departure.time = int(departure.timestamp())
    return TransitTripUpdatesResponse(feed.SerializeToString())


class EnRouteFromFeedTest(unittest.TestCase):
    def _en_route_by_route(self, *trips):
        stop_visits = _feed(*trips).convert_to_display_info_dict([_STOP])[_STOP].stop_visit_list
        return {stop_visit.line_reference: stop_visit.en_route for stop_visit in stop_visits}

    def test_a_trip_still_at_its_first_stop_is_not_en_route(self):
        leaves = _NOW + timedelta(minutes=10)
        en_route = self._en_route_by_route(
            ("48", [(1, "terminal", None, leaves), (6, _STOP, leaves + timedelta(minutes=6), leaves)]),
        )
        self.assertEqual(en_route, {"48": False})

    def test_a_trip_past_its_first_stop_is_en_route(self):
        # the feed drops stops a bus has passed, so its first listed stop is the next one, with an arrival time
        next_stop = _NOW + timedelta(minutes=1)
        en_route = self._en_route_by_route(
            ("48", [(3, "next", next_stop, next_stop), (6, _STOP, next_stop + timedelta(minutes=3), None)]),
        )
        self.assertEqual(en_route, {"48": True})

    def test_a_trip_whose_first_stop_is_not_numbered_1_is_judged_by_its_times(self):
        leaves = _NOW + timedelta(minutes=4)
        en_route = self._en_route_by_route(
            ("9", [(2, "terminal", None, leaves), (5, _STOP, leaves + timedelta(minutes=5), None)]),
        )
        self.assertEqual(en_route, {"9": False})

    def test_a_late_bus_still_at_its_first_stop_is_not_en_route(self):
        # its scheduled departure has passed, but the feed still lists the first stop
        left_late = _NOW - timedelta(minutes=2)
        en_route = self._en_route_by_route(
            ("48", [(1, "terminal", None, left_late), (6, _STOP, _NOW + timedelta(minutes=4), None)]),
        )
        self.assertEqual(en_route, {"48": False})


class RowSegmentsTest(unittest.TestCase):
    # "44" uses the first column of each digit cell, the closest a time's pixels come to the marker
    _TIMES = [_NOW + timedelta(minutes=4, seconds=30), _NOW + timedelta(minutes=44, seconds=30)]
    _LINE = "48 04 44"

    def _segments(self, en_route, indicator):
        with mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", indicator):
            return main.get_row_draw_segments(self._LINE, self._TIMES, en_route, (150, 30, 0), 8, _NOW)

    def _pixels(self, segments):
        canvas = FakeCanvas()
        main.draw_display_frame(canvas, _font(), [segments], (63, 31), (0, 0, 0))
        del canvas.pixels[(63, 31)]
        return canvas.pixels

    def test_no_markers_with_the_indicator_off(self):
        segments = self._segments([True, True], 0)
        self.assertNotIn(main.EN_ROUTE_MARKER, [text for *_, text in segments])

    def test_markers_only_for_buses_en_route(self):
        segments = self._segments([False, True], 1)
        markers = [segment for segment in segments if segment[3] == main.EN_ROUTE_MARKER]
        second_time_x_pos = segments[2][0]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0][0], second_time_x_pos - 3)

    def test_markers_leave_the_text_segments_unchanged(self):
        without_markers = self._segments([True, True], 0)
        with_markers = self._segments([True, True], 1)
        # identifier first and leading time second, which the pulse and departure animation rely on
        self.assertEqual(with_markers[: len(without_markers)], without_markers)

    def test_markers_never_touch_or_move_the_text(self):
        text_pixels = self._pixels(self._segments([True, True], 0))
        all_pixels = self._pixels(self._segments([True, True], 1))
        marker_pixels = {xy: rgb for xy, rgb in all_pixels.items() if xy not in text_pixels}
        self.assertEqual({xy: all_pixels[xy] for xy in text_pixels}, text_pixels)
        self.assertEqual(len(marker_pixels), 8)
        # a blank column always separates each marker pixel from every text pixel, side by side and diagonally
        for marker_x, marker_y in marker_pixels:
            for text_x, text_y in text_pixels:
                self.assertFalse(abs(marker_x - text_x) <= 1 and abs(marker_y - text_y) <= 1)


class TowedRowTest(unittest.TestCase):
    def test_towed_times_keep_their_markers(self):
        due = _NOW
        en_route_later = _NOW + timedelta(minutes=12, seconds=30)
        waiting_later = _NOW + timedelta(minutes=31, seconds=30)
        snapshot = {
            _STOP: DisplayInfoModel(
                response_timestamp=_NOW,
                stop_visit_list=[
                    StopVisitModel(line_reference="48", expected_arrival_time=due, en_route=True),
                    StopVisitModel(line_reference="48", expected_arrival_time=en_route_later, en_route=True),
                    StopVisitModel(line_reference="48", expected_arrival_time=waiting_later, en_route=False),
                ],
            )
        }
        times = [due + timedelta(seconds=1), en_route_later, waiting_later]
        en_route = [True, True, False]
        with (
            mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", 1),
            mock.patch.object(main, "display_info_dict", snapshot),
            mock.patch.object(main, "datetime", wraps=datetime) as patched_datetime,
            mock.patch.object(main, "play_departure_animation") as play,
        ):
            patched_datetime.now.return_value = _NOW + timedelta(seconds=1)
            row_segments = main.get_row_draw_segments("48 00 12", times[:2], en_route[:2], (150, 30, 0), 8, _NOW)
            main.play_departure_animation_for_due_arrivals(
                None,
                "canvas",
                _font(),
                due,
                [times],
                [en_route],
                [(_STOP, "48")],
                [main.AnimationDirection.LEFT_TO_RIGHT],
                [row_segments],
                (63, 31),
                (0, 0, 0),
            )
        towed_segments = play.call_args.args[3][0].towed_segments
        towed_texts = [text for *_, text in towed_segments]
        # 12 is towed in with its marker, and 31 without one
        self.assertEqual(towed_texts, ["48 ", "12", "31", main.EN_ROUTE_MARKER])
        self.assertEqual(towed_segments[3][0], towed_segments[1][0] - 3)


if __name__ == "__main__":
    unittest.main()
