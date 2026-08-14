from http import HTTPMethod
from typing import Any, Literal

import httpx
from httpx_retries import Retry, RetryTransport

from models.OpenData511 import TransitStopMonitoringResponse
from modules.logger import logger


class OpenData511Client:
    def __init__(self, api_token: str) -> None:
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
            base_url="https://api.511.org",
            params={"api_key": api_token},
            transport=retry_transport,
            timeout=timeout_config,
        )

    def _authenticated_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = self._client.request(method, path, params=params, json=json_payload)
        # log text, not .json(): non-JSON error bodies would raise here and mask the real status code
        logger.debug(f"Response body: {response.text}")
        if response.status_code == 401:
            raise httpx.HTTPStatusError(
                "401 Unauthorized: OpenData511 api key is missing or invalid",
                request=response.request,
                response=response,
            )
        else:
            response.raise_for_status()
        return response

    def get_transit_stop_monitoring(
        self,
        agency: str,
        stopcode: str | int | None = None,
        format: Literal["json", "xml"] = "json",
    ):
        response = self._authenticated_request(
            "get",
            "/transit/StopMonitoring",
            params={
                "agency": agency,
                "stopcode": stopcode,
                "format": format,
            },
        )
        return TransitStopMonitoringResponse.model_validate(response.json())
