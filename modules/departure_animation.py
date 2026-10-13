from dataclasses import dataclass, field
from time import monotonic, sleep

from modules.animation_player import FRAMES_PER_SECOND
from modules.environment import DEPARTURE_ANIMATION_SPRITE_LIST
from modules.sprites import SPRITE_COLOR_LEGEND, SPRITES_BY_NAME, AnimationDirection, Convoy, build_convoy, draw_convoy

_TRAVEL_DURATION_SECONDS = 2.0
_ENTRY_EXIT_BUFFER_SECONDS = 0.5  # row fade-out before the convoy enters, settle time after it exits
DEPARTURE_ANIMATION_DURATION_SECONDS = _TRAVEL_DURATION_SECONDS + 2 * _ENTRY_EXIT_BUFFER_SECONDS
_TOW_GAP_PIXELS = 5  # gap between the last vehicle and the row contents it tows

# fail fast at startup on configured sprite names which don't name a sprite, environment.py cannot
# validate these itself without a circular import
for _sprite_name in DEPARTURE_ANIMATION_SPRITE_LIST:
    if _sprite_name not in SPRITES_BY_NAME:
        raise ValueError(
            f"Environment variable DEPARTURE_ANIMATION_SPRITES entry '{_sprite_name}' is not a valid sprite name, "
            f"valid names are {','.join(SPRITES_BY_NAME)}"
        )
_DEPARTURE_SPRITE_NAMES = tuple(DEPARTURE_ANIMATION_SPRITE_LIST)


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


def _draw_convoy_towing_row(canvas, animation_row: DepartureAnimationRow, convoy: Convoy, row_height: int, display_width: int, travel_percent: float, draw_segments):
    """Draws one row's convoy at its position along its travel with the row's towed contents behind it"""
    # travel from fully off-screen to far enough past the other edge that the towed contents, which
    # trail behind the convoy and stop at their resting positions, are fully towed into place
    if animation_row.direction == AnimationDirection.LEFT_TO_RIGHT:
        convoy_end_x_pos = max(display_width, animation_row.towed_right_x + _TOW_GAP_PIXELS)
        convoy_x_pos = -convoy.width + int((convoy_end_x_pos + convoy.width) * travel_percent)
        tow_x_offset = min(convoy_x_pos - _TOW_GAP_PIXELS - animation_row.towed_right_x, 0)
        rope_x_range = range(animation_row.towed_right_x + tow_x_offset, convoy_x_pos)
        still_towing = tow_x_offset < 0
    else:
        convoy_end_x_pos = min(-convoy.width, animation_row.towed_left_x - _TOW_GAP_PIXELS - convoy.width)
        convoy_x_pos = display_width - int((display_width - convoy_end_x_pos) * travel_percent)
        tow_x_offset = max(convoy_x_pos + convoy.width + _TOW_GAP_PIXELS - animation_row.towed_left_x, 0)
        rope_x_range = range(convoy_x_pos + convoy.width, animation_row.towed_left_x + tow_x_offset)
        still_towing = tow_x_offset > 0

    # vehicles ride along the bottom of the row so all wheels share a common road line
    draw_convoy(canvas, convoy, convoy_x_pos, animation_row.row_y_pos + row_height)

    draw_segments(canvas, animation_row.towed_segments, 1.0, tow_x_offset)
    if still_towing and animation_row.towed_segments:
        # a small tow rope between the last vehicle and the row contents it is towing
        rope_y_pos = animation_row.row_y_pos + (row_height // 2)
        for rope_x_pos in rope_x_range:
            canvas.SetPixel(rope_x_pos, rope_y_pos, *SPRITE_COLOR_LEGEND["K"])


def draw_convoy_pass_frame(canvas, sprite_names: tuple[str, ...], direction: AnimationDirection, display_width: int, display_height: int, elapsed_seconds: float):
    """Draws one frame of a convoy driving across the vertical center of an otherwise blank display

    This is the loading screen's pass, shared with the convoy event animation so both drive exactly alike. It
    lasts DEPARTURE_ANIMATION_DURATION_SECONDS, blank for the entry buffer, then the convoy crosses.

    Args:
        canvas: cleared canvas to draw the frame on
        sprite_names (tuple[str, ...]): sprites in the convoy, leading sprite first
        direction (AnimationDirection): the direction the convoy drives
        display_width (int): width of the display in pixels
        display_height (int): height of the display in pixels
        elapsed_seconds (float): time since the pass started
    """
    row_height = build_convoy(sprite_names, direction).height
    _draw_departure_frame(
        canvas,
        elapsed_seconds,
        display_width,
        [DepartureAnimationRow(row_y_pos=(display_height - row_height) // 2, direction=direction)],
        row_height,
        lambda animation_canvas: None,  # nothing but the convoy on a blank display
        lambda animation_canvas, segments, brightness_percent, x_offset: None,  # nothing to fade or tow
        sprite_names,
    )


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
    return _play_frames(
        matrix,
        canvas,
        lambda animation_canvas, elapsed_seconds: draw_convoy_pass_frame(
            animation_canvas,
            _DEPARTURE_SPRITE_NAMES,
            AnimationDirection.LEFT_TO_RIGHT,
            display_width,
            display_height,
            elapsed_seconds,
        ),
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
    return _play_frames(
        matrix,
        canvas,
        lambda animation_canvas, elapsed_seconds: _draw_departure_frame(
            animation_canvas,
            elapsed_seconds,
            display_width,
            animation_row_list,
            row_height,
            draw_background,
            draw_segments,
            _DEPARTURE_SPRITE_NAMES,
        ),
    )


def _draw_departure_frame(canvas, elapsed_seconds: float, display_width: int, animation_row_list: list[DepartureAnimationRow], row_height: int, draw_background, draw_segments, sprite_names: tuple[str, ...]):
    """Draws one frame of convoys driving through display rows, see play_departure_animation"""
    travel_elapsed_seconds = elapsed_seconds - _ENTRY_EXIT_BUFFER_SECONDS
    travel_percent = min(max(travel_elapsed_seconds / _TRAVEL_DURATION_SECONDS, 0.0), 1.0)

    draw_background(canvas)
    if travel_percent == 0:
        # rows fade out before their convoys enter the display
        fade_brightness_percent = max(1 - (elapsed_seconds / _ENTRY_EXIT_BUFFER_SECONDS), 0.0)
        for animation_row in animation_row_list:
            draw_segments(canvas, animation_row.fading_segments, fade_brightness_percent, 0)
    else:
        for animation_row in animation_row_list:
            convoy = build_convoy(sprite_names, animation_row.direction)
            _draw_convoy_towing_row(canvas, animation_row, convoy, row_height, display_width, travel_percent, draw_segments)


def _play_frames(matrix, canvas, draw_frame):
    """Swaps frames drawn by draw_frame(canvas, elapsed_seconds) onto the display for one animation's duration"""
    start_time = monotonic()
    while (elapsed_seconds := monotonic() - start_time) < DEPARTURE_ANIMATION_DURATION_SECONDS:
        canvas.Clear()
        draw_frame(canvas, elapsed_seconds)
        canvas = matrix.SwapOnVSync(canvas)

        sleep(1 / FRAMES_PER_SECOND)

    return canvas
