"""banner: text scrolling right to left across the middle of the panel at a fixed 60 px/s

It always uses the 5x7 font, whatever FONT is set to, so its width and the contract's duration formula hold. The
text starts a margin past the right edge and the request ends once it is a margin past the left edge, so it never
pops into or out of view, even when the Pi draws a frame late. At 60 px/s, 103 characters is the most that fits in
the 10 s cap.
"""

from pydantic import BaseModel, ConfigDict, Field

from modules.animation_player import Animation, AnimationContext, RGBColor
from modules.display_utils import cap_if_enabled, get_text_center_y_pos
from modules.rgbmatrix_importer import get_rgb_matrix_imports

_, _, graphics = get_rgb_matrix_imports()

SCROLL_PIXELS_PER_SECOND = 60
CHARACTER_WIDTH_PIXELS = 5
# blank travel before the text enters and after it leaves, about a sixth of a second at 60 px/s
EDGE_MARGIN_PIXELS = 10
_CHARACTER_HEIGHT_PIXELS = 7
# the most text that scrolls fully across the 64 px panel and both margins within the 10 s cap: (10 * 60 - 64 - 20) // 5
TEXT_MAX_CHARACTERS = 103


class BannerParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    # printable ASCII only, a simple closed contract for publishers to sanitize against
    text: str = Field(min_length=1, max_length=TEXT_MAX_CHARACTERS, pattern=r"^[\x20-\x7e]+$")
    color: RGBColor = (255, 255, 255)


def _duration_seconds(params: BannerParams):
    # the contract's display width is 64, the panel this was built for
    distance_pixels = EDGE_MARGIN_PIXELS + 64 + CHARACTER_WIDTH_PIXELS * len(params.text) + EDGE_MARGIN_PIXELS
    return distance_pixels / SCROLL_PIXELS_PER_SECOND


def _draw_frame(canvas, elapsed_seconds: float, params: BannerParams, context: AnimationContext):
    x_pos = context.width + EDGE_MARGIN_PIXELS - int(elapsed_seconds * SCROLL_PIXELS_PER_SECOND)
    y_pos = get_text_center_y_pos(_CHARACTER_HEIGHT_PIXELS, context.height)
    graphics.DrawText(canvas, context.font_5x7, x_pos, y_pos, graphics.Color(*cap_if_enabled(params.color)), params.text)


ANIMATION = Animation("banner", BannerParams, _duration_seconds, _draw_frame)
