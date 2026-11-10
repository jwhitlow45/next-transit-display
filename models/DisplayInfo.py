from datetime import datetime
from typing import List

from pydantic import BaseModel


class StopVisitModel(BaseModel):
    # recorded_at: datetime
    line_reference: str
    # line_name: str
    # monitored: bool
    # in_congestion: bool | None
    # occupancy: OpenData511Models.OccupancyEnum | None
    # vehicle_at_stop: bool | None
    # aimed_arrival_time: datetime | None
    expected_arrival_time: datetime | None
    # aimed_departure_time: datetime | None
    # the bus running this trip has left the first stop of its route, as far as the 511 feeds show
    en_route: bool = False


class DisplayInfoModel(BaseModel):
    response_timestamp: datetime
    stop_visit_list: List[StopVisitModel]
