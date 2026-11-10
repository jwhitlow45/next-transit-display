from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2

import models.DisplayInfo as DisplayInfoModels


def is_en_route(stop_time_update_list, vehicle_stop_sequence: int | None):
    """Whether the bus running a trip has left the first stop of its route

    The vehicle's own position decides when the vehicle positions feed has one for the trip. The trip updates feed
    gets the start of a route wrong both ways: it drops the stop a bus is standing at, so a late bus still boarding at
    its first stop already looks gone, and it can predict a bus running far behind from mid-route while the bus is
    still driving to the start. Without a vehicle, the trip updates feed is all there is: a trip that hasn't started
    lists its first stop with only a departure time, and drops that stop once the bus pulls away
    """
    if len(stop_time_update_list) == 0:
        return False
    first_listed = stop_time_update_list[0]
    if vehicle_stop_sequence is None:
        return first_listed.arrival.HasField("time")
    first_stop_listed = first_listed.departure.HasField("time") and not first_listed.arrival.HasField("time")
    # once the trip updates feed drops the first stop its number is gone, so it is taken to be 1, which the agency's
    # trips start at all but a handful of times
    first_stop_sequence = first_listed.stop_sequence if first_stop_listed else 1
    return vehicle_stop_sequence > first_stop_sequence


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

    def convert_to_display_info_dict(
        self, stopcode_list: list[str], vehicle_stop_sequence_dict: dict[str, int] | None = None
    ):
        """Collects the predicted visits to each given stopcode from every trip in the feed

        Every stopcode gets an entry, even without upcoming visits, so the status LED sees it was refreshed.
        vehicle_stop_sequence_dict, from TransitVehiclePositionsResponse, decides which buses are en route
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
            en_route = is_en_route(stop_time_update_list, (vehicle_stop_sequence_dict or {}).get(trip.trip_id))
            for stop_time_update in stop_time_update_list:
                if (
                    stop_time_update.stop_id not in display_info_dict
                    or stop_time_update.schedule_relationship == gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED
                ):
                    continue
                # a trip's first stop only has a departure time
                stop_time_event = (
                    stop_time_update.arrival
                    if stop_time_update.arrival.HasField("time")
                    else stop_time_update.departure
                )
                if not stop_time_event.HasField("time"):
                    continue
                display_info_dict[stop_time_update.stop_id].stop_visit_list.append(
                    DisplayInfoModels.StopVisitModel(
                        line_reference=trip.route_id,
                        expected_arrival_time=datetime.fromtimestamp(stop_time_event.time, timezone.utc),
                        en_route=en_route,
                    )
                )
        return display_info_dict
