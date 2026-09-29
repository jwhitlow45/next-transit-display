from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2

import models.DisplayInfo as DisplayInfoModels


# GTFS-realtime protobuf rather than JSON, so this wraps the parsed feed instead of being a pydantic model.
# Trip updates are used over stop monitoring because stop monitoring only publishes a few predictions per
# line, while trip updates predict every upcoming stop of every trip the agency is running
class TransitTripUpdatesResponse:
    def __init__(self, content: bytes) -> None:
        self.feed_message = gtfs_realtime_pb2.FeedMessage()
        self.feed_message.ParseFromString(content)

    def convert_to_display_info_dict(self, stopcode_list: list[str]):
        """Collects the predicted visits to each given stopcode from every trip in the feed

        Every stopcode gets an entry, even without upcoming visits, so the status LED sees it was refreshed
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
            for stop_time_update in entity.trip_update.stop_time_update:
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
                    )
                )
        return display_info_dict
