from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic, sleep

from modules.display_utils import Colors

_TRAVEL_DURATION_SECONDS = 2.0
_ENTRY_EXIT_BUFFER_SECONDS = 0.5  # row fade-out before the convoy enters, settle time after it exits
DEPARTURE_ANIMATION_DURATION_SECONDS = _TRAVEL_DURATION_SECONDS + 2 * _ENTRY_EXIT_BUFFER_SECONDS
_FRAMES_PER_SECOND = 30
_VEHICLE_GAP_PIXELS = 6
_TOW_GAP_PIXELS = 5  # gap between the last vehicle and the row contents it tows


class AnimationDirection(StrEnum):
    LEFT_TO_RIGHT = "R"
    RIGHT_TO_LEFT = "L"


# "." pixels are transparent, every other character is drawn with its legend color
_SPRITE_COLOR_LEGEND = {
    "R": Colors.RED,
    "S": Colors.SILVER,
    "Y": Colors.YELLOW,
    "G": Colors.GREEN,
    "C": Colors.CREAM,
    "B": Colors.BLUE,
    "K": Colors.GRAY,
    "D": (70, 70, 70),  # dark window glass, not part of Colors as it is too dim for text
    "W": Colors.WHITE,
}

# NOTE: sprites are 7 pixels tall to fill one row of a 7 pixel tall font, taller fonts leave headroom
# in the row while shorter fonts will have the convoy spill into neighboring rows

# muni-style bus: silver with a red band, lit windows, headlight up front
_BUS_SPRITE = [
    ".RRRRRRRRRRRR.",
    ".SSSSSSSSSSSS.",
    ".SYYSYYSYYSYS.",
    ".SYYSYYSYYSYS.",
    ".RRRRRRRRRRRW.",
    ".SSSSSSSSSSSS.",
    "..KK......KK..",
]

# f-line-style streetcar: green over cream with lit windows
_STREETCAR_SPRITE = [
    "..GGGGGGGGGGGG..",
    ".GGGGGGGGGGGGGG.",
    ".GYYGYYGYYGYYGG.",
    ".GYYGYYGYYGYYGG.",
    ".CCCCCCCCCCCCCC.",
    ".GGGGGGGGGGGGGG.",
    "..KK........KK..",
]

# bart-style subway car: silver with dark windows and a blue stripe
_SUBWAY_CAR_SPRITE = [
    "..SSSSSSSSSSSS..",
    ".SSSSSSSSSSSSSS.",
    ".SDDSSDDSSDDSSS.",
    ".SBBBBBBBBBBBBS.",
    ".SSSSSSSSSSSSSS.",
    ".SSSSSSSSSSSSSS.",
    "..KK........KK..",
]

# sprites are drawn facing right and drive left to right with the bus leading, so it sits rightmost
_CONVOY_LEFT_TO_RIGHT = [_SUBWAY_CAR_SPRITE, _STREETCAR_SPRITE, _BUS_SPRITE]
# mirror the sprites and reverse their order so the bus still leads when driving right to left
_CONVOY_RIGHT_TO_LEFT = [[row[::-1] for row in sprite] for sprite in reversed(_CONVOY_LEFT_TO_RIGHT)]
_CONVOY_BY_DIRECTION = {
    AnimationDirection.LEFT_TO_RIGHT: _CONVOY_LEFT_TO_RIGHT,
    AnimationDirection.RIGHT_TO_LEFT: _CONVOY_RIGHT_TO_LEFT,
}
_CONVOY_WIDTH = sum(max(len(row) for row in sprite) for sprite in _CONVOY_LEFT_TO_RIGHT) + _VEHICLE_GAP_PIXELS * (
    len(_CONVOY_LEFT_TO_RIGHT) - 1
)


def _get_convoy_x_offsets(convoy: list[list[str]]):
    """Calculates the x offset of each vehicle in a convoy relative to the convoy's left edge"""
    x_offsets: list[int] = []
    next_x_offset = 0
    for sprite in convoy:
        x_offsets.append(next_x_offset)
        next_x_offset += max(len(row) for row in sprite) + _VEHICLE_GAP_PIXELS
    return x_offsets


_CONVOY_X_OFFSETS_BY_DIRECTION = {
    direction: _get_convoy_x_offsets(convoy) for direction, convoy in _CONVOY_BY_DIRECTION.items()
}


@dataclass
class DepartureAnimationRow:
    """A display row for the departure animation to drive through

    row_y_pos is the y position of the top of the row's band of pixels and direction is the direction
    the convoy drives through it. fading_segments are the row's current (x, y, rgb, text) contents,
    faded out before the convoy enters. towed_segments are the row's post-departure contents positioned
    at their final resting places, towed into place behind the convoy, with towed_left_x/towed_right_x
    their resting pixel bounds.
    """

    row_y_pos: int
    direction: AnimationDirection
    fading_segments: list[tuple[int, int, tuple[int, int, int], str]] = field(default_factory=list)
    towed_segments: list[tuple[int, int, tuple[int, int, int], str]] = field(default_factory=list)
    towed_left_x: int = 0
    towed_right_x: int = 0


def _draw_sprite(canvas, sprite: list[str], x_pos: int, y_pos: int):
    """Draws a sprite onto a canvas with its top-left corner at (x_pos, y_pos)

    Args:
        canvas: canvas to draw the sprite onto, out of bounds pixels are clipped by SetPixel
        sprite (list[str]): rows of sprite characters, see _SPRITE_COLOR_LEGEND
        x_pos (int): x position of the top-left corner of the sprite
        y_pos (int): y position of the top-left corner of the sprite
    """
    for y_offset, row in enumerate(sprite):
        for x_offset, char in enumerate(row):
            if char != ".":
                canvas.SetPixel(x_pos + x_offset, y_pos + y_offset, *_SPRITE_COLOR_LEGEND[char])


def _draw_convoy_towing_row(canvas, animation_row: DepartureAnimationRow, row_height: int, display_width: int, travel_percent: float, draw_segments):
    """Draws one row's convoy at its position along its travel with the row's towed contents behind it"""
    # travel from fully off-screen to far enough past the other edge that the towed contents, which
    # trail behind the convoy and stop at their resting positions, are fully towed into place
    if animation_row.direction == AnimationDirection.LEFT_TO_RIGHT:
        convoy_end_x_pos = max(display_width, animation_row.towed_right_x + _TOW_GAP_PIXELS)
        convoy_x_pos = -_CONVOY_WIDTH + int((convoy_end_x_pos + _CONVOY_WIDTH) * travel_percent)
        tow_x_offset = min(convoy_x_pos - _TOW_GAP_PIXELS - animation_row.towed_right_x, 0)
        rope_x_range = range(animation_row.towed_right_x + tow_x_offset, convoy_x_pos)
        still_towing = tow_x_offset < 0
    else:
        convoy_end_x_pos = min(-_CONVOY_WIDTH, animation_row.towed_left_x - _TOW_GAP_PIXELS - _CONVOY_WIDTH)
        convoy_x_pos = display_width - int((display_width - convoy_end_x_pos) * travel_percent)
        tow_x_offset = max(convoy_x_pos + _CONVOY_WIDTH + _TOW_GAP_PIXELS - animation_row.towed_left_x, 0)
        rope_x_range = range(convoy_x_pos + _CONVOY_WIDTH, animation_row.towed_left_x + tow_x_offset)
        still_towing = tow_x_offset > 0

    # vehicles ride along the bottom of the row so all wheels share a common road line
    road_y_pos = animation_row.row_y_pos + row_height
    convoy = _CONVOY_BY_DIRECTION[animation_row.direction]
    for sprite, sprite_x_offset in zip(convoy, _CONVOY_X_OFFSETS_BY_DIRECTION[animation_row.direction]):
        _draw_sprite(canvas, sprite, convoy_x_pos + sprite_x_offset, road_y_pos - len(sprite))

    draw_segments(canvas, animation_row.towed_segments, 1.0, tow_x_offset)
    if still_towing and animation_row.towed_segments:
        # a small tow rope between the last vehicle and the row contents it is towing
        rope_y_pos = animation_row.row_y_pos + (row_height // 2)
        for rope_x_pos in rope_x_range:
            canvas.SetPixel(rope_x_pos, rope_y_pos, *_SPRITE_COLOR_LEGEND["K"])


def play_loading_animation(matrix, canvas, display_width: int, display_height: int):
    """Plays one pass of the transit convoy driving across the vertical center of the display

    Intended to be looped as a loading screen while waiting for the first stop data to arrive

    Args:
        matrix: RGBMatrix object to swap animation frames onto
        canvas: back buffer canvas to draw the next frame on
        display_width (int): width of the display in pixels
        display_height (int): height of the display in pixels

    Returns:
        canvas: back buffer canvas returned by the final frame swap, use this in place of the canvas passed in
    """
    row_height = max(len(sprite) for sprite in _CONVOY_LEFT_TO_RIGHT)
    row_y_pos = (display_height - row_height) // 2
    return play_departure_animation(
        matrix,
        canvas,
        display_width,
        [DepartureAnimationRow(row_y_pos=row_y_pos, direction=AnimationDirection.LEFT_TO_RIGHT)],
        row_height,
        lambda animation_canvas: None,  # nothing but the convoy on a blank display
        lambda animation_canvas, segments, brightness_percent, x_offset: None,  # nothing to fade or tow
    )


def play_departure_animation(matrix, canvas, display_width: int, animation_row_list: list[DepartureAnimationRow], row_height: int, draw_background, draw_segments):
    """Plays an animation of convoys of transit vehicles driving through display rows

    Intended to play when displayed arrival times reach 0. Each row's current contents fade out, then a
    convoy drives through the row in its direction towing the row's post-departure contents behind it,
    which settle into their resting positions as the convoy drives off the display. draw_background
    re-draws the rest of the display each frame so only the animated rows change.

    Args:
        matrix: RGBMatrix object to swap animation frames onto
        canvas: back buffer canvas to draw the next frame on
        display_width (int): width of the display in pixels
        animation_row_list (list[DepartureAnimationRow]): the display rows to drive through
        row_height (int): height of a display row in pixels
        draw_background: callable which draws the non-animated display contents onto the canvas passed to it
        draw_segments: callable which draws (canvas, segments, brightness_percent, x_offset), used to
            fade out each row's current contents and to draw its towed contents mid-tow

    Returns:
        canvas: back buffer canvas returned by the final frame swap, use this in place of the canvas passed in
    """
    start_time = monotonic()
    while (elapsed_seconds := monotonic() - start_time) < DEPARTURE_ANIMATION_DURATION_SECONDS:
        travel_elapsed_seconds = elapsed_seconds - _ENTRY_EXIT_BUFFER_SECONDS
        travel_percent = min(max(travel_elapsed_seconds / _TRAVEL_DURATION_SECONDS, 0.0), 1.0)

        canvas.Clear()
        draw_background(canvas)
        if travel_percent == 0:
            # rows fade out before their convoys enter the display
            fade_brightness_percent = max(1 - (elapsed_seconds / _ENTRY_EXIT_BUFFER_SECONDS), 0.0)
            for animation_row in animation_row_list:
                draw_segments(canvas, animation_row.fading_segments, fade_brightness_percent, 0)
        else:
            for animation_row in animation_row_list:
                _draw_convoy_towing_row(canvas, animation_row, row_height, display_width, travel_percent, draw_segments)
        canvas = matrix.SwapOnVSync(canvas)

        sleep(1 / _FRAMES_PER_SECOND)

    return canvas
