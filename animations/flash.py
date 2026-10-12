"""flash: the whole panel filled with each color in turn, held at least 500 ms per color

The 500 ms floor keeps it at two color changes a second, under the usual three a second photosensitivity limit.
Every fill goes through fill_panel and its power guard, see FILL_CHANNEL_CAP in modules/animation_player.py.
"""

from pydantic import BaseModel, ConfigDict, Field

from modules.animation_player import Animation, AnimationContext, RGBColor, fill_panel
from modules.display_utils import cap_if_enabled


class FlashParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    colors: tuple[RGBColor, ...] = Field(min_length=1, max_length=20)
    step_ms: int = Field(default=700, ge=500, le=2000)
    repeats: int = Field(default=1, ge=1, le=4)


def _duration_seconds(params: FlashParams):
    return len(params.colors) * params.step_ms * params.repeats / 1000


def _draw_frame(canvas, elapsed_seconds: float, params: FlashParams, context: AnimationContext):
    step_index = int(elapsed_seconds * 1000 // params.step_ms) % len(params.colors)
    fill_panel(canvas, cap_if_enabled(params.colors[step_index]))


ANIMATION = Animation("flash", FlashParams, _duration_seconds, _draw_frame)
