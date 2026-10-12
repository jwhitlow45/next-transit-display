"""convoy: any sprites driving across the middle of a blank panel, as the loading screen's convoy does"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.animation_player import Animation, AnimationContext
from modules.departure_animation import DEPARTURE_ANIMATION_DURATION_SECONDS, draw_convoy_pass_frame
from modules.sprites import SPRITES_BY_NAME, AnimationDirection


class ConvoyParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    # leading sprite first, as in DEPARTURE_ANIMATION_SPRITES
    sprites: tuple[str, ...] = Field(min_length=1, max_length=6)
    direction: Literal["R", "L"] = "R"

    @field_validator("sprites")
    @classmethod
    def _sprites_are_known(cls, sprites: tuple[str, ...]):
        unknown_sprites = [sprite for sprite in sprites if sprite not in SPRITES_BY_NAME]
        if unknown_sprites:
            raise ValueError(f"unknown sprites {unknown_sprites!r}")
        return sprites


def _duration_seconds(params: ConvoyParams):
    return DEPARTURE_ANIMATION_DURATION_SECONDS


def _draw_frame(canvas, elapsed_seconds: float, params: ConvoyParams, context: AnimationContext):
    draw_convoy_pass_frame(
        canvas,
        params.sprites,
        AnimationDirection(params.direction),
        context.width,
        context.height,
        elapsed_seconds,
    )


ANIMATION = Animation("convoy", ConvoyParams, _duration_seconds, _draw_frame)
