from datetime import datetime
from enum import StrEnum
from typing import Annotated, List

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
