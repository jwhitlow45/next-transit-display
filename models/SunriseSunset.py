from datetime import datetime

from pydantic import BaseModel


class SunriseSunsetResult(BaseModel):
    sunrise: datetime
    sunset: datetime
    solar_noon: datetime
    day_length: int
    civil_twilight_begin: datetime
    civil_twilight_end: datetime
    nautical_twilight_begin: datetime
    nautical_twilight_end: datetime
    astronomical_twilight_begin: datetime
    astronomical_twilight_end: datetime


class SunriseSunsetResponse(BaseModel):
    results: SunriseSunsetResult
    status: str
    tzid: str
