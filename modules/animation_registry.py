"""The animations the display can play, and the intake that turns a published payload into a queued request

The intake is transport-agnostic: the MQTT listener is a thin adapter that hands it each payload, so another
transport could be added without touching validation, the queue, or playback.
"""

import json
import logging
from time import monotonic
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from animations import banner, convoy, flash
from modules.animation_player import Animation, AnimationRequest
from modules.animation_queue import AnimationQueue

logger = logging.getLogger(__name__)

# contract version 1 constants, publishers rely on these so they are not configuration
CONTRACT_VERSION = 1
PAYLOAD_MAX_BYTES = 4096
MAX_DURATION_SECONDS = 10.0
# the Pi reports under-voltage on its normal load and flash adds full-panel fills to it. J accepted that and asked
# for flash to stay on, setting this False refuses flash requests with a logged reason
FLASH_ENABLED = True
_REJECTION_LOG_INTERVAL_SECONDS = 60
_LOGGED_PAYLOAD_MAX_CHARACTERS = 200

# adding an animation means adding a module to animations/ and a line here
ANIMATIONS: dict[str, Animation] = {
    animation.name: animation for animation in (convoy.ANIMATION, flash.ANIMATION, banner.ANIMATION)
}


class RejectedRequest(ValueError):
    """A payload that breaks the animation contract, with the reason it was refused"""


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    v: int
    animation: str
    params: dict[str, Any] = Field(default_factory=dict)


def _describe_errors(err: ValidationError):
    # locations only, never pydantic's messages, which quote the publisher's input into the log
    return repr([".".join(str(part) for part in error["loc"]) for error in err.errors()])


def parse_request(payload: bytes):
    """Validates a published payload against the contract

    Raises:
        RejectedRequest: the payload breaks the contract, with the reason

    Returns:
        AnimationRequest: the request, ready to queue
    """
    if len(payload) > PAYLOAD_MAX_BYTES:
        raise RejectedRequest(f"payload of {len(payload)} bytes is over the {PAYLOAD_MAX_BYTES} byte cap")
    try:
        envelope = _Envelope.model_validate_json(payload)
    except ValidationError as err:
        raise RejectedRequest(f"not a version {CONTRACT_VERSION} request, invalid at {_describe_errors(err)}") from None
    if envelope.v != CONTRACT_VERSION:
        raise RejectedRequest(f"unknown contract version {envelope.v}")

    animation = ANIMATIONS.get(envelope.animation)
    if animation is None:
        raise RejectedRequest(f"unknown animation {envelope.animation[:40]!r}")
    if animation is flash.ANIMATION and not FLASH_ENABLED:
        raise RejectedRequest("flash is disabled, see FLASH_ENABLED in modules/animation_registry.py")

    # params go back through JSON so strict validation sees JSON types: arrays for colors, and no 1.0 or true
    # where an integer belongs
    try:
        params = animation.params_model.model_validate_json(json.dumps(envelope.params))
    except ValidationError as err:
        raise RejectedRequest(f"invalid {animation.name} params at {_describe_errors(err)}") from None

    duration_seconds = animation.duration_seconds(params)
    if duration_seconds > MAX_DURATION_SECONDS:
        raise RejectedRequest(
            f"{animation.name} would play {duration_seconds:.2f} s, over the {MAX_DURATION_SECONDS:.0f} s cap"
        )
    return AnimationRequest(animation, params, duration_seconds, f"{animation.name}:{params.model_dump_json()}")


class AnimationIntake:
    """Validates published payloads and queues the valid ones, logging rejections at most once a minute

    The rate limit keeps a looping or broken publisher from filling the Pi's SD card with log lines. Payloads are
    logged as a cut repr(), so a crafted newline can't forge a log line either
    """

    def __init__(self, queue: AnimationQueue, clock=monotonic):
        self._queue = queue
        self._clock = clock
        self._last_rejection_logged_at: float | None = None
        self._unlogged_rejections = 0

    def submit(self, payload: bytes):
        try:
            request = parse_request(payload)
        except RejectedRequest as rejection:
            self._log_rejection(str(rejection), payload)
            return
        if not self._queue.put(request):
            logger.debug(f"Animation request coalesced into an equal one already waiting: {request.animation.name}")

    def _log_rejection(self, reason: str, payload: bytes):
        self._unlogged_rejections += 1
        now = self._clock()
        if (
            self._last_rejection_logged_at is not None
            and now - self._last_rejection_logged_at < _REJECTION_LOG_INTERVAL_SECONDS
        ):
            return
        logger.warning(
            f"Rejected {self._unlogged_rejections} animation request(s) since the last report, latest: {reason}, "
            f"payload {repr(payload)[:_LOGGED_PAYLOAD_MAX_CHARACTERS]}"
        )
        self._last_rejection_logged_at = now
        self._unlogged_rejections = 0
