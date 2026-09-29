from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, List

from google.transit import gtfs_realtime_pb2
from pydantic import BaseModel, BeforeValidator, Field

import models.DisplayInfo as DisplayInfoModels


def boolean_parser(v: bool | str):
    if type(v) is bool:
        return v
    return True if v == "true" or v == "True" else False


class VehicleLocationModel(BaseModel):
    Longitude: str | None = Field(None)
    Latitude: str | None = Field(None)


class MonitoredCallModel(BaseModel):
    StopPointRef: str
    StopPointName: str
    VehicleLocationAtStop: str | None = Field(None)
    VehicleAtStop: Annotated[bool, BeforeValidator(boolean_parser)]
    DestinationDisplay: str | None = Field(None)
    AimedArrivalTime: datetime | None = Field(None)
    ExpectedArrivalTime: datetime | None = Field(None)
    AimedDepartureTime: datetime | None = Field(None)
    ExpectedDepartureTime: datetime | None = Field(None)
    Distances: str | None = Field(None)


class FramedVehicleJourneyRefModel(BaseModel):
    DataFrameRef: datetime
    DatedVehicleJourneyRef: str


class OccupancyEnum(StrEnum):
    FULL = "full"
    SEATS_AVAILABLE = "seatsAvailable"
    STANDING_AVAILABLE = "standingAvailable"


class MonitoredVehicleJourneyModel(BaseModel):
    LineRef: str
    DirectionRef: str
    FramedVehicleJourneyRef: FramedVehicleJourneyRefModel
    PublishedLineName: str
    OperatorRef: str
    OriginRef: str | None = Field(None)
    OriginName: str | None = Field(None)
    DestinationRef: str | None = Field(None)
    DestinationName: str | None = Field(None)
    Monitored: Annotated[bool, BeforeValidator(boolean_parser)]
    InCongestion: Annotated[bool, BeforeValidator(boolean_parser)] | None = Field(None)
    VehicleLocation: VehicleLocationModel | None
    Bearing: float | None = Field(None)
    Occupancy: OccupancyEnum | None = Field(None)
    VehicleRef: str | None = Field(None)
    MonitoredCall: MonitoredCallModel | None


class MonitoredStopVisitModel(BaseModel):
    RecordedAtTime: datetime
    MonitoringRef: str
    MonitoredVehicleJourney: MonitoredVehicleJourneyModel | None


class StopMonitoringDeliveryModel(BaseModel):
    version: str
    ResponseTimestamp: datetime
    Status: bool
    # default to empty so responses with no upcoming visits (e.g. overnight) don't fail validation
    MonitoredStopVisit: List[MonitoredStopVisitModel] = []
    # NOTE: Intentionally omitting MonitoredStopVisitCancellation, StopLineNotice, and StopLineNoticeCancellation for simplicity


class ServiceDeliveryModel(BaseModel):
    ResponseTimestamp: datetime
    ProducerRef: str
    Status: bool
    StopMonitoringDelivery: StopMonitoringDeliveryModel


class TransitStopMonitoringResponse(BaseModel):
    ServiceDelivery: ServiceDeliveryModel

    def convert_to_display_info(self):
        stop_monitoring = self.ServiceDelivery.StopMonitoringDelivery
        response_timestamp = stop_monitoring.ResponseTimestamp
        stop_visit_list = [
            DisplayInfoModels.StopVisitModel(
                # recorded_at=stop_visit.RecordedAtTime,
                line_reference=stop_visit.MonitoredVehicleJourney.LineRef,
                # line_name=stop_visit.MonitoredVehicleJourney.PublishedLineName,
                # monitored=stop_visit.MonitoredVehicleJourney.Monitored,
                # in_congestion=stop_visit.MonitoredVehicleJourney.InCongestion,
                # occupancy=stop_visit.MonitoredVehicleJourney.Occupancy,
                # vehicle_at_stop=stop_visit.MonitoredVehicleJourney.MonitoredCall.VehicleAtStop
                # if stop_visit.MonitoredVehicleJourney.MonitoredCall
                # else None,
                # aimed_arrival_time=stop_visit.MonitoredVehicleJourney.MonitoredCall.AimedArrivalTime
                # if stop_visit.MonitoredVehicleJourney.MonitoredCall
                # else None,
                expected_arrival_time=stop_visit.MonitoredVehicleJourney.MonitoredCall.ExpectedArrivalTime
                if stop_visit.MonitoredVehicleJourney.MonitoredCall
                else None,
                # aimed_departure_time=stop_visit.MonitoredVehicleJourney.MonitoredCall.AimedDepartureTime
                # if stop_visit.MonitoredVehicleJourney.MonitoredCall
                # else None,
            )
            for stop_visit in stop_monitoring.MonitoredStopVisit
            if stop_visit.MonitoredVehicleJourney  # optional from API so ensure existence
        ]

        return DisplayInfoModels.DisplayInfoModel(
            response_timestamp=response_timestamp, stop_visit_list=stop_visit_list
        )


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
