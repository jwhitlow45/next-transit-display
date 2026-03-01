from datetime import datetime, timedelta

from pydantic import BaseModel, computed_field

from modules.environment import APPROXIMATE_AVERAGE_SUNSET_LENGTH_SECONDS


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def approximate_full_daylight_offset(self) -> timedelta:
        """Approximate offset after sunrise/before sunset when the beginning/end of full daylight is"""
        return timedelta(seconds=int(APPROXIMATE_AVERAGE_SUNSET_LENGTH_SECONDS * self.day_length / 43200))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def approximate_full_daylight_begin(self) -> datetime:
        """Approximate beginning of full daylight"""
        return self.sunrise + self.approximate_full_daylight_offset

    @computed_field  # type: ignore[prop-decorator]
    @property
    def approximate_full_daylight_end(self) -> datetime:
        """Approximate end of full daylight"""
        return self.sunset - self.approximate_full_daylight_offset

    @computed_field  # type: ignore[prop-decorator]
    @property
    def no_light_to_full_daylight_timedelta(self) -> timedelta:
        return self.approximate_full_daylight_begin - self.nautical_twilight_begin

    @computed_field  # type: ignore[prop-decorator]
    @property
    def full_daylight_to_no_light_timedelta(self) -> timedelta:
        return self.nautical_twilight_end - self.approximate_full_daylight_end


class SunriseSunsetResponse(BaseModel):
    results: SunriseSunsetResult
    status: str
    tzid: str
