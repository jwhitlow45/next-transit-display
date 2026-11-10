import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fakes import FakeCanvas, FakeMatrix
from google.transit import gtfs_realtime_pb2

import main
from models.DisplayInfo import DisplayInfoModel, StopVisitModel
from models.OpenData511 import TransitTripUpdatesResponse, TransitVehiclePositionsResponse

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


def _vehicle_positions(trip_stop_sequences, timestamp=_NOW):
    """A vehicle positions feed of {trip_id: current_stop_sequence}"""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(timestamp.timestamp())
    for trip_id, stop_sequence in trip_stop_sequences.items():
        entity = feed.entity.add()
        entity.id = f"vehicle {trip_id}"
        entity.vehicle.trip.trip_id = trip_id
        entity.vehicle.current_stop_sequence = stop_sequence
    return TransitVehiclePositionsResponse(feed.SerializeToString())


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


class EnRouteFromVehicleTest(unittest.TestCase):
    """With a vehicle for the trip, its position decides, whatever the trip updates feed suggests"""

    def _en_route(self, stop_time_updates, vehicle_stop_sequences):
        stop_visits = (
            _feed(("48", stop_time_updates))
            .convert_to_display_info_dict([_STOP], vehicle_stop_sequences)[_STOP]
            .stop_visit_list
        )
        return stop_visits[0].en_route

    def test_a_late_bus_boarding_at_its_first_stop_is_not_en_route(self):
        # the trip updates feed drops the stop a bus is standing at, so it already lists the second stop
        soon = _NOW + timedelta(minutes=1)
        trip = [(2, "second", soon, soon), (6, _STOP, soon + timedelta(minutes=5), None)]
        self.assertFalse(self._en_route(trip, {"0": 1}))

    def test_a_bus_still_driving_to_the_start_is_not_en_route(self):
        # running far behind, the trip updates feed predicts it from mid-route
        soon = _NOW + timedelta(minutes=1)
        trip = [(44, "mid-route", soon, soon), (50, _STOP, soon + timedelta(minutes=5), None)]
        self.assertFalse(self._en_route(trip, {"0": 1}))

    def test_a_bus_past_its_first_stop_is_en_route_before_the_trip_updates_feed_catches_up(self):
        leaves = _NOW + timedelta(seconds=50)
        trip = [(1, "terminal", None, leaves), (6, _STOP, leaves + timedelta(minutes=6), None)]
        self.assertTrue(self._en_route(trip, {"0": 2}))

    def test_a_trip_whose_first_stop_is_numbered_2(self):
        leaves = _NOW + timedelta(minutes=1)
        trip = [(2, "terminal", None, leaves), (5, _STOP, leaves + timedelta(minutes=5), None)]
        self.assertFalse(self._en_route(trip, {"0": 2}))
        self.assertTrue(self._en_route(trip, {"0": 3}))

    def test_a_trip_without_a_vehicle_falls_back_to_the_trip_updates_feed(self):
        soon = _NOW + timedelta(minutes=1)
        trip = [(3, "next", soon, soon), (6, _STOP, soon + timedelta(minutes=3), None)]
        self.assertTrue(self._en_route(trip, {"another trip": 1}))


class RememberedFirstStopTest(unittest.TestCase):
    """A trip whose first stop isn't numbered 1 keeps that number once the trip updates feed drops the stop"""

    _LEAVES = _NOW + timedelta(minutes=1)
    _BEFORE = [(2, "terminal", None, _LEAVES), (5, _STOP, _LEAVES + timedelta(minutes=5), None)]
    _AFTER = [(3, "next", _LEAVES, _LEAVES), (5, _STOP, _LEAVES + timedelta(minutes=5), None)]

    def _en_route_after_dropping_the_first_stop(self, vehicle_stop_sequence, seen_before):
        first_stop_sequence_dict: dict[str, int] = {}
        if seen_before:
            _feed(("9", self._BEFORE)).remember_first_stop_sequences(first_stop_sequence_dict)
        after = _feed(("9", self._AFTER))
        after.remember_first_stop_sequences(first_stop_sequence_dict)
        stop_visits = after.convert_to_display_info_dict(
            [_STOP], {"0": vehicle_stop_sequence}, first_stop_sequence_dict
        )[_STOP].stop_visit_list
        return stop_visits[0].en_route

    def test_a_bus_boarding_at_a_first_stop_numbered_2_is_not_en_route(self):
        self.assertFalse(self._en_route_after_dropping_the_first_stop(2, seen_before=True))
        self.assertTrue(self._en_route_after_dropping_the_first_stop(3, seen_before=True))

    def test_a_trip_first_seen_without_its_first_stop_takes_it_to_be_1(self):
        self.assertTrue(self._en_route_after_dropping_the_first_stop(2, seen_before=False))

    def test_trips_that_leave_the_feed_are_forgotten(self):
        first_stop_sequence_dict = {"gone": 1}
        _feed(("9", self._BEFORE)).remember_first_stop_sequences(first_stop_sequence_dict)
        self.assertEqual(first_stop_sequence_dict, {"0": 2})


class VehiclePositionsTest(unittest.TestCase):
    def test_only_vehicles_with_a_trip_and_a_stop_count(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = int(_NOW.timestamp())
        running = feed.entity.add()
        running.id = "running"
        running.vehicle.trip.trip_id = "a"
        running.vehicle.current_stop_sequence = 3
        no_trip = feed.entity.add()
        no_trip.id = "no trip"
        no_trip.vehicle.current_stop_sequence = 4
        no_stop = feed.entity.add()
        no_stop.id = "no stop"
        no_stop.vehicle.trip.trip_id = "b"
        vehicle_positions = TransitVehiclePositionsResponse(feed.SerializeToString())
        self.assertEqual(vehicle_positions.get_trip_stop_sequence_dict(), {"a": 3})

    def test_positions_too_old_are_not_used(self):
        max_age = main._VEHICLE_POSITIONS_MAX_AGE_REFRESHES * main.env.REFRESH_API_INTERVAL_SECONDS
        now = datetime.now(timezone.utc)
        fresh = _vehicle_positions({"a": 3}, now - timedelta(seconds=max_age - 5))
        stale = _vehicle_positions({"a": 3}, now - timedelta(seconds=max_age + 5))
        self.assertEqual(main.get_fresh_vehicle_stop_sequence_dict(fresh), {"a": 3})
        self.assertIsNone(main.get_fresh_vehicle_stop_sequence_dict(stale))
        self.assertIsNone(main.get_fresh_vehicle_stop_sequence_dict(None))


class _StopLoop(Exception):
    pass


class ApiLoopRequestsTest(unittest.TestCase):
    """Which requests api_loop makes, and with which key, over a number of refreshes"""

    def _requests(self, indicator, refreshes):
        requests = []
        vehicle_dicts = []

        class FakeTripUpdates:
            def remember_first_stop_sequences(self, first_stop_sequence_dict):
                pass

            def convert_to_display_info_dict(
                self, stopcode_list, vehicle_stop_sequence_dict=None, first_stop_sequence_dict=None
            ):
                vehicle_dicts.append(vehicle_stop_sequence_dict)
                return {}

        class FakeClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def get_transit_trip_updates(self, agency):
                requests.append((self.api_key, "trip updates"))
                return FakeTripUpdates()

            def get_transit_vehicle_positions(self, agency):
                requests.append((self.api_key, "vehicle positions"))
                return _vehicle_positions({"a": 3}, datetime.now(timezone.utc))

        sleeps = []

        def fake_sleep(_seconds):
            sleeps.append(_seconds)
            if len(sleeps) == refreshes:
                raise _StopLoop

        with (
            mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", indicator),
            mock.patch.object(main.env, "OPEN_DATA_511_API_KEY_LIST", ["k0", "k1", "k2", "k3"]),
            mock.patch.object(main, "OpenData511Client", FakeClient),
            mock.patch.object(main, "sleep", fake_sleep),
            mock.patch.object(main, "display_info_dict", None),
        ):
            with self.assertRaises(_StopLoop):
                main.api_loop()
        return requests, vehicle_dicts

    def test_off_makes_one_trip_updates_request_per_refresh_round_robin(self):
        requests, vehicle_dicts = self._requests(0, 4)
        self.assertEqual(requests, [(key, "trip updates") for key in ("k0", "k1", "k2", "k3")])
        self.assertEqual(vehicle_dicts, [None] * 4)

    def test_on_adds_vehicle_positions_every_other_refresh_spread_across_the_keys(self):
        requests, vehicle_dicts = self._requests(1, 8)
        kinds = [kind for _, kind in requests]
        self.assertEqual(kinds.count("trip updates"), 8)
        self.assertEqual(kinds.count("vehicle positions"), 4)
        self.assertEqual(requests[:3], [("k0", "vehicle positions"), ("k1", "trip updates"), ("k2", "trip updates")])
        for key in ("k0", "k1", "k2", "k3"):
            self.assertEqual(sum(1 for request_key, _ in requests if request_key == key), 3)
        # refreshes between vehicle positions requests use the last positions fetched
        self.assertEqual(vehicle_dicts, [{"a": 3}] * 8)


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


class DisplayRowsTest(unittest.TestCase):
    def test_en_route_flags_line_up_with_the_times_and_follow_the_displayed_subset(self):
        times = [_NOW + timedelta(minutes=minutes, seconds=30) for minutes in (4, 12, 31)]
        snapshot = {
            _STOP: DisplayInfoModel(
                response_timestamp=_NOW,
                stop_visit_list=[
                    # out of time order, which build_display_rows sorts
                    StopVisitModel(line_reference="48", expected_arrival_time=times[1], en_route=False),
                    StopVisitModel(line_reference="48", expected_arrival_time=times[2], en_route=True),
                    StopVisitModel(line_reference="48", expected_arrival_time=times[0], en_route=True),
                ],
            )
        }
        rows = main.build_display_rows(snapshot, _NOW, 4)
        self.assertEqual(rows[1], [times])
        self.assertEqual(rows[5], [[True, False, True]])
        with mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", 1):
            segments = main.get_display_line_draw_args(rows[0], rows[1], rows[5], rows[3], _font(), _NOW)[0]
        # FUTURE_STOP_VISITS_SHOWN is 2 in the test environment, so 31 and its marker aren't displayed
        markers = [segment for segment in segments if segment[3] == main.EN_ROUTE_MARKER]
        self.assertEqual([text for *_, text in segments], ["48 ", "O4", "12", main.EN_ROUTE_MARKER])
        self.assertEqual(markers[0][0], segments[1][0] - 3)


class MarkerDrawingTest(unittest.TestCase):
    def test_a_dimmed_and_shifted_marker_draws_where_and_how_the_animation_asks(self):
        # the departure animation fades and tows rows by passing draw_segment a dimmed color and a shifted x
        canvas = FakeCanvas()
        main.draw_segment(canvas, _font(), 20 + 7, 8, (60, 12, 0), main.EN_ROUTE_MARKER)
        self.assertEqual(
            canvas.pixels, {(27, 3): (60, 12, 0), (27, 4): (60, 12, 0), (28, 4): (60, 12, 0), (27, 5): (60, 12, 0)}
        )

    def test_the_leading_times_marker_pulses_with_it(self):
        times = [_NOW + timedelta(seconds=3), _NOW + timedelta(minutes=12, seconds=30)]
        with mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", 1):
            row_segments = main.get_row_draw_segments("48 OO 12", times, [True, True], (150, 30, 0), 8, _NOW)
        matrix = FakeMatrix()
        with (
            mock.patch.object(main, "datetime", wraps=datetime) as patched_datetime,
            # half a pulse in, where the pulse is at its dimmest
            mock.patch.object(main, "monotonic", side_effect=[0.0, 0.5 / main.env.PULSE_FREQUENCY_HZ]),
            mock.patch.object(main, "sleep"),
        ):
            patched_datetime.now.side_effect = [_NOW, _NOW, times[0]]
            main.pulse_imminent_arrivals(
                matrix, FakeCanvas(), _font(), times[0], [times], [row_segments], (63, 31), (0, 0, 0)
            )
        frame = matrix.frames[0]
        # the leading time, due now, is in the run color, and only it and its marker dim
        _, _, leading_rgb, _ = row_segments[1]
        dimmed_leading_rgb = tuple(int(channel * main.env.PULSE_MIN_BRIGHTNESS_PERCENT) for channel in leading_rgb)
        self.assertEqual(frame[(row_segments[1][0] - 3, 4)], dimmed_leading_rgb)
        self.assertEqual(frame[(row_segments[2][0] - 3, 4)], row_segments[2][2])


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

    def test_without_fresh_data_for_the_stop_the_rows_own_flags_are_used(self):
        due = _NOW
        times = [
            due + timedelta(seconds=1),
            _NOW + timedelta(minutes=12, seconds=30),
            _NOW + timedelta(minutes=31, seconds=30),
        ]
        en_route = [True, False, True]
        with (
            mock.patch.object(main.env, "ENABLE_EN_ROUTE_INDICATOR", 1),
            mock.patch.object(main, "display_info_dict", {}),
            mock.patch.object(main, "datetime", wraps=datetime) as patched_datetime,
            mock.patch.object(main, "play_departure_animation") as play,
        ):
            patched_datetime.now.return_value = _NOW + timedelta(seconds=1)
            row_segments = main.get_row_draw_segments("48 OO 12", times[:2], en_route[:2], (150, 30, 0), 8, _NOW)
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
        # 12 without a marker, 31 with one
        self.assertEqual([text for *_, text in towed_segments], ["48 ", "12", "31", main.EN_ROUTE_MARKER])
        self.assertEqual(towed_segments[3][0], towed_segments[2][0] - 3)


if __name__ == "__main__":
    unittest.main()
