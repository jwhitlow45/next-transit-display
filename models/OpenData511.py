from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from google.transit import gtfs_realtime_pb2

import models.DisplayInfo as DisplayInfoModels

# how long before the trip updates feed expects it a bus can set off from the start of its route. Buses rarely leave
# early, and the feed's departure time can trail a bus that has just left by a refresh or two
_EARLIEST_DEPARTURE_LEAD = timedelta(minutes=2)
# how far a bus that has just left the start of its route can be from the next stop it lists. Routes reach their second
# stop within 5 minutes, apart from route 25, whose first stretch crosses the Bay Bridge in about 12. A route 25 bus
# without a vehicle position gets its marker a few minutes late there, rather than raising the limit for every route
_LONGEST_TIME_TO_NEXT_STOP = timedelta(minutes=10)
# the furthest stop a bus waiting at the start of its route lists next: stop 2, or stop 3 for the route 9 trips that
# hold at stop 2
_LAST_STOP_LISTED_WHILE_WAITING = 3


class StartingStop(NamedTuple):
    stop_sequence: int
    departure_time: datetime


def get_starting_stop(stop_time_update_list) -> StartingStop | None:
    """The stop a trip that hasn't started sets off from, and when the feed expects it to, or None once the trip
    updates feed shows it started

    A trip that hasn't started lists its first stop with only a departure time. Some route 9 trips also list their
    second stop that way, where the bus holds before setting off, so a trip sets off from the last of those stops
    """
    starting_stop = None
    for stop_time_update in stop_time_update_list:
        if stop_time_update.arrival.HasField("time") or not stop_time_update.departure.HasField("time"):
            break
        starting_stop = StartingStop(
            stop_time_update.stop_sequence, datetime.fromtimestamp(stop_time_update.departure.time, timezone.utc)
        )
    return starting_stop


def _listed_time(stop_time_update) -> datetime | None:
    # a trip's first stop only has a departure time
    stop_time_event = (
        stop_time_update.arrival if stop_time_update.arrival.HasField("time") else stop_time_update.departure
    )
    if not stop_time_event.HasField("time"):
        return None
    return datetime.fromtimestamp(stop_time_event.time, timezone.utc)


def is_en_route(
    stop_time_update_list,
    now: datetime,
    vehicle_stop_sequence: int | None,
    remembered_starting_stop: StartingStop | None = None,
):
    """Whether the bus running a trip has set off from the start of its route

    The vehicle's own position decides when the vehicle positions feed has one for the trip. The trip updates feed
    drops the stop a bus is standing at, so a late bus still boarding at its first stop already looks gone there, and
    it can also lag a bus that has just left. Without a vehicle, the trip updates feed is all there is: a trip that
    hasn't started lists its first stop with only a departure time, and drops that stop once the bus pulls away. As it
    also drops that stop while the bus waits there, its times have to agree the bus has left, see _could_have_left

    now is the trip updates feed's own time. remembered_starting_stop is the trip's starting stop from an earlier
    refresh, see TransitTripUpdatesResponse.remember_starting_stops
    """
    if len(stop_time_update_list) == 0:
        return False
    first_listed = stop_time_update_list[0]
    starting_stop = get_starting_stop(stop_time_update_list) or remembered_starting_stop
    if vehicle_stop_sequence is None:
        return first_listed.arrival.HasField("time") and _could_have_left(first_listed, starting_stop, now)
    # As a bus nears the last stop of its trip, the vehicle positions feed numbers that stop 1, most likely as the
    # first stop of the bus's next trip. So a trip down to its last stop is en route whatever the vehicle says
    if len(stop_time_update_list) == 1:
        return first_listed.arrival.HasField("time")
    # A trip without a starting stop was first seen after it dropped it, which only happens to trips already running
    # when the display starts. It is taken to set off from stop 1, as the agency's trips do apart from the route 9
    # trips that hold at stop 2, so after a restart such a bus holding at stop 2 can be marked early. Taking the stop
    # before the first listed one instead would blink the marker off at every stop such a bus makes
    starting_stop_sequence = starting_stop.stop_sequence if starting_stop is not None else 1
    return vehicle_stop_sequence > starting_stop_sequence


def _could_have_left(first_listed, starting_stop: StartingStop | None, now: datetime):
    """Whether the trip updates feed's times allow that a trip with no vehicle position has left the start of its route

    A bus that has left set off no earlier than shortly before the feed expected it to. A restart forgets the starting
    stops the feed had already dropped, so a bus waiting at the start of its route is also told apart by how far off
    the next stop it lists is
    """
    if starting_stop is not None and starting_stop.departure_time - now > _EARLIEST_DEPARTURE_LEAD:
        return False
    if first_listed.stop_sequence > _LAST_STOP_LISTED_WHILE_WAITING:
        return True
    first_listed_time = _listed_time(first_listed)
    return first_listed_time is None or first_listed_time - now <= _LONGEST_TIME_TO_NEXT_STOP


class TransitVehiclePositionsResponse:
    def __init__(self, content: bytes) -> None:
        self.feed_message = gtfs_realtime_pb2.FeedMessage()
        self.feed_message.ParseFromString(content)
        self.response_timestamp = datetime.fromtimestamp(self.feed_message.header.timestamp, timezone.utc)

    def get_trip_stop_sequence_dict(self) -> dict[str, int]:
        """Maps each trip a vehicle reports running to the stop_sequence of the stop the vehicle is at or heading to"""
        return {
            entity.vehicle.trip.trip_id: entity.vehicle.current_stop_sequence
            for entity in self.feed_message.entity
            if entity.vehicle.trip.trip_id and entity.vehicle.HasField("current_stop_sequence")
        }


# GTFS-realtime protobuf rather than JSON, so this wraps the parsed feed instead of being a pydantic model.
# Trip updates are used over stop monitoring because stop monitoring only publishes a few predictions per
# line, while trip updates predict every upcoming stop of every trip the agency is running
class TransitTripUpdatesResponse:
    def __init__(self, content: bytes) -> None:
        self.feed_message = gtfs_realtime_pb2.FeedMessage()
        self.feed_message.ParseFromString(content)

    def remember_starting_stops(self, starting_stop_dict: dict[str, StartingStop]):
        """Records, in place, the latest starting stop of every trip that still lists one, and forgets trips no longer
        in the feed

        The feed drops a trip's starting stop, its number and departure time with it, once the bus boards there or
        leaves. The route 9 trips that hold at stop 2 list stop 1 first and stop 2 once stop 1 is dropped, so the
        latest one is kept
        """
        trip_id_set = set()
        for entity in self.feed_message.entity:
            trip_id = entity.trip_update.trip.trip_id
            trip_id_set.add(trip_id)
            starting_stop = get_starting_stop(entity.trip_update.stop_time_update)
            if starting_stop is not None:
                starting_stop_dict[trip_id] = starting_stop
        for trip_id in list(starting_stop_dict):
            if trip_id not in trip_id_set:
                del starting_stop_dict[trip_id]

    def convert_to_display_info_dict(
        self,
        stopcode_list: list[str],
        vehicle_stop_sequence_dict: dict[str, int] | None = None,
        starting_stop_dict: dict[str, StartingStop] | None = None,
    ):
        """Collects the predicted visits to each given stopcode from every trip in the feed

        Every stopcode gets an entry, even without upcoming visits, so the status LED sees it was refreshed.
        vehicle_stop_sequence_dict, from TransitVehiclePositionsResponse, and starting_stop_dict, from
        remember_starting_stops, decide which buses are en route
        """
        response_timestamp = datetime.fromtimestamp(self.feed_message.header.timestamp, timezone.utc)
        display_info_dict = {
            stopcode: DisplayInfoModels.DisplayInfoModel(response_timestamp=response_timestamp, stop_visit_list=[])
            for stopcode in stopcode_list
        }
        for entity in self.feed_message.entity:
            trip = entity.trip_update.trip
            # canceled and deleted trips will not arrive
            if trip.schedule_relationship in (
                gtfs_realtime_pb2.TripDescriptor.CANCELED,
                gtfs_realtime_pb2.TripDescriptor.DELETED,
            ):
                continue
            stop_time_update_list = entity.trip_update.stop_time_update
            en_route = is_en_route(
                stop_time_update_list,
                response_timestamp,
                (vehicle_stop_sequence_dict or {}).get(trip.trip_id),
                (starting_stop_dict or {}).get(trip.trip_id),
            )
            for stop_time_update in stop_time_update_list:
                if (
                    stop_time_update.stop_id not in display_info_dict
                    or stop_time_update.schedule_relationship == gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED
                ):
                    continue
                expected_arrival_time = _listed_time(stop_time_update)
                if expected_arrival_time is None:
                    continue
                display_info_dict[stop_time_update.stop_id].stop_visit_list.append(
                    DisplayInfoModels.StopVisitModel(
                        line_reference=trip.route_id,
                        expected_arrival_time=expected_arrival_time,
                        en_route=en_route,
                    )
                )
        return display_info_dict
