from time import monotonic, sleep

from modules.display_utils import Colors

_TRAVEL_DURATION_SECONDS = 2.0
_ENTRY_EXIT_BUFFER_SECONDS = 0.5  # blank row held before the convoy enters and after it exits
DEPARTURE_ANIMATION_DURATION_SECONDS = _TRAVEL_DURATION_SECONDS + 2 * _ENTRY_EXIT_BUFFER_SECONDS
_FRAMES_PER_SECOND = 30
_VEHICLE_GAP_PIXELS = 6

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

# vehicles drive left to right with the bus leading, so it sits rightmost in the layout
_CONVOY = [_SUBWAY_CAR_SPRITE, _STREETCAR_SPRITE, _BUS_SPRITE]


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


def play_departure_animation(matrix, canvas, display_width: int, row_y_pos_list: list[int], row_height: int, draw_background):
    """Plays an animation of a convoy of transit vehicles driving through display rows

    Intended to play when a displayed arrival time reaches 0, right before it disappears from the display.
    The convoy drives through the display rows starting at each y position in row_y_pos_list while
    draw_background re-draws the rest of the display each frame, erasing only the animated rows for the
    duration of the animation.

    Args:
        matrix: RGBMatrix object to swap animation frames onto
        canvas: back buffer canvas to draw the next frame on
        display_width (int): width of the display in pixels
        row_y_pos_list (list[int]): y positions of the tops of the display rows to drive through
        row_height (int): height of a display row in pixels
        draw_background: callable which draws the non-animated display contents onto the canvas passed to it

    Returns:
        canvas: back buffer canvas returned by the final frame swap, use this in place of the canvas passed in
    """
    sprite_widths = [max(len(row) for row in sprite) for sprite in _CONVOY]
    convoy_width = sum(sprite_widths) + _VEHICLE_GAP_PIXELS * (len(_CONVOY) - 1)

    sprite_x_offsets: list[int] = []
    next_x_offset = 0
    for sprite_width in sprite_widths:
        sprite_x_offsets.append(next_x_offset)
        next_x_offset += sprite_width + _VEHICLE_GAP_PIXELS

    # travel from fully off-screen left to fully off-screen right, clamping travel_percent so the
    # entry/exit buffer periods hold a blank row on either side of the crossing
    travel_distance = display_width + convoy_width
    start_time = monotonic()
    while (elapsed_seconds := monotonic() - start_time) < DEPARTURE_ANIMATION_DURATION_SECONDS:
        travel_elapsed_seconds = elapsed_seconds - _ENTRY_EXIT_BUFFER_SECONDS
        travel_percent = min(max(travel_elapsed_seconds / _TRAVEL_DURATION_SECONDS, 0.0), 1.0)
        convoy_x_pos = -convoy_width + int(travel_distance * travel_percent)

        canvas.Clear()
        draw_background(canvas)
        for row_y_pos in row_y_pos_list:
            # vehicles ride along the bottom of the row so all wheels share a common road line
            road_y_pos = row_y_pos + row_height
            for sprite, sprite_x_offset in zip(_CONVOY, sprite_x_offsets):
                _draw_sprite(canvas, sprite, convoy_x_pos + sprite_x_offset, road_y_pos - len(sprite))
        canvas = matrix.SwapOnVSync(canvas)

        sleep(1 / _FRAMES_PER_SECOND)

    return canvas
