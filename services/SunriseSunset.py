from http import HTTPMethod
from typing import Any

import httpx
from httpx_retries import Retry, RetryTransport

from models.SunriseSunset import SunriseSunsetResponse
from modules.logger import logger


class SunriseSunsetClient:
    def __init__(self) -> None:
        exponential_retry_policy = Retry(
            total=3,
            allowed_methods=[HTTPMethod.GET],
            status_forcelist=[500, 502, 503, 504],
            backoff_factor=1,
            respect_retry_after_header=True,
            max_backoff_wait=10,
            backoff_jitter=1,
        )
        retry_transport = RetryTransport(retry=exponential_retry_policy)
        timeout_config = httpx.Timeout(timeout=10.0)
        self._client = httpx.Client(
            base_url="https://api.sunrise-sunset.org",
            transport=retry_transport,
            timeout=timeout_config,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = self._client.request(method, path, params=params, json=json_payload)
        logger.debug(f"Response json: {response.json()}")
        response.raise_for_status()
        return response

    def get_solar_time_data(self, lat: float, lng: float, date: str = "today", tzid: str = "UTC"):
        response = self._request(
            "get",
            "/json",
            params={
                "lat": lat,
                "lng": lng,
                "date": date,
                "formatted": 0,  # hard-code for easier str -> datetime coercion
                "tzid": tzid,
            },
        )
        return SunriseSunsetResponse.model_validate(response.json())
