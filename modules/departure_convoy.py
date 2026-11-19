"""The departure convoy a publisher can swap in, such as a themed one while something in the house needs attention

Like the animation intake it is transport-agnostic: the MQTT listener only hands it each payload. The listener
clears the swap on every connect and its retained subscription restores it, so a reboot keeps the last swap and a
clear published while the display was offline still ends it.
"""

import logging
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from modules.rate_limited_log import RateLimitedLog
from modules.sprites import SPRITES_BY_NAME

logger = logging.getLogger(__name__)

CONTRACT_VERSION = 1
PAYLOAD_MAX_BYTES = 4096
_LOGGED_PAYLOAD_MAX_CHARACTERS = 200


class DepartureConvoyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    v: int
    # leading sprite first, as in DEPARTURE_ANIMATION_SPRITES. Bounded like the convoy animation, so a publisher
    # can't make the convoy too long to read as it drives through a row
    sprites: tuple[str, ...] = Field(min_length=1, max_length=6)

    @field_validator("sprites")
    @classmethod
    def _sprites_are_known(cls, sprites: tuple[str, ...]):
        unknown_sprites = [sprite for sprite in sprites if sprite not in SPRITES_BY_NAME]
        if unknown_sprites:
            raise ValueError(f"unknown sprites {unknown_sprites!r}")
        return sprites


class DepartureConvoy:
    """The last valid convoy a publisher swapped in, or None, when departures drive the configured one

    submit runs on paho's network thread and swapped_sprite_names on the display thread. The swap replaces one
    tuple reference, which Python does atomically, so neither side needs a lock.
    """

    def __init__(self, clock=monotonic):
        self._swapped_sprite_names: tuple[str, ...] | None = None
        self._rejection_log = RateLimitedLog(logger, logging.WARNING, clock=clock)

    def swapped_sprite_names(self) -> tuple[str, ...] | None:
        return self._swapped_sprite_names

    def submit(self, payload: bytes):
        # an empty payload is how MQTT clears a retained message, so it also clears the swap
        if payload == b"":
            if self._swapped_sprite_names is not None:
                logger.info("Departure convoy back to the configured one")
            self._swapped_sprite_names = None
            return
        try:
            sprite_names = _parse(payload)
        except ValueError as rejection:
            # a bad request keeps the current convoy rather than clearing it, so a typo can't undo a swap
            self._rejection_log.record(
                f"Rejected a departure convoy: {rejection}, payload {repr(payload)[:_LOGGED_PAYLOAD_MAX_CHARACTERS]}"
            )
            return
        if sprite_names != self._swapped_sprite_names:
            logger.info(f"Departure convoy swapped to {','.join(sprite_names)}")
        self._swapped_sprite_names = sprite_names


def _parse(payload: bytes):
    if len(payload) > PAYLOAD_MAX_BYTES:
        raise ValueError(f"payload of {len(payload)} bytes is over the {PAYLOAD_MAX_BYTES} byte cap")
    try:
        request = DepartureConvoyRequest.model_validate_json(payload)
    except ValidationError as err:
        # locations only: pydantic's messages would repeat the publisher's values in the log
        locations = [".".join(str(part) for part in error["loc"]) for error in err.errors()]
        raise ValueError(f"not a version {CONTRACT_VERSION} departure convoy, invalid at {locations!r}") from None
    if request.v != CONTRACT_VERSION:
        raise ValueError(f"unknown contract version {request.v}")
    return request.sprites
