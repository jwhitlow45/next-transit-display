from time import monotonic, sleep

from modules.display_utils import Colors

DEPARTURE_ANIMATION_DURATION_SECONDS = 2.0
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

# muni-style bus: silver with a red band, lit windows, headlight up front
_BUS_SPRITE = [
    "..RRRRRRRRRRRR..",
    ".SSSSSSSSSSSSSS.",
    ".SYYSYYSYYSSYYS.",
    ".SYYSYYSYYSSYYS.",
    ".SSSSSSSSSSSSSS.",
    ".RRRRRRRRRRRRRR.",
    ".SSSSSSSSSSSSSW.",
    "..KKK......KKK..",
    "...K........K...",
]

# f-line-style streetcar: green over cream with a trolley pole trailing behind
_STREETCAR_SPRITE = [
    "......K...........",
    ".......K..........",
    "........K.........",
    "..GGGGGGGGGGGGGG..",
    ".GGGGGGGGGGGGGGGG.",
    ".GYYGYYGYYGYYGYYG.",
    ".GYYGYYGYYGYYGYYG.",
    ".CCCCCCCCCCCCCCCC.",
    ".GGGGGGGGGGGGGGGG.",
    "..KKK........KKK..",
    "...K..........K...",
]

# bart-style subway car: silver with dark windows and a blue stripe
_SUBWAY_CAR_SPRITE = [
    "..SSSSSSSSSSSSSS..",
    ".SSSSSSSSSSSSSSSS.",
    ".SDDDSDDDSDDDSDDS.",
    ".SBBBBBBBBBBBBBBS.",
    ".SSSSSSSSSSSSSSSS.",
    ".SSSSSSSSSSSSSSSS.",
    "..KKK........KKK..",
    "...K..........K...",
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


def play_departure_animation(matrix, canvas, display_width: int, display_height: int):
    """Plays an animation of a convoy of transit vehicles driving across the center of the display

    Intended to play when a displayed arrival time reaches 0, right before it disappears from the display

    Args:
        matrix: RGBMatrix object to swap animation frames onto
        canvas: back buffer canvas to draw the next frame on
        display_width (int): width of the display in pixels
        display_height (int): height of the display in pixels

    Returns:
        canvas: back buffer canvas returned by the final frame swap, use this in place of the canvas passed in
    """
    sprite_widths = [max(len(row) for row in sprite) for sprite in _CONVOY]
    sprite_heights = [len(sprite) for sprite in _CONVOY]
    convoy_width = sum(sprite_widths) + _VEHICLE_GAP_PIXELS * (len(_CONVOY) - 1)

    # all vehicles sit on a common road line vertically centered on the display
    road_y_pos = (display_height + max(sprite_heights)) // 2

    sprite_x_offsets: list[int] = []
    next_x_offset = 0
    for sprite_width in sprite_widths:
        sprite_x_offsets.append(next_x_offset)
        next_x_offset += sprite_width + _VEHICLE_GAP_PIXELS

    # travel from fully off-screen left to fully off-screen right
    travel_distance = display_width + convoy_width
    start_time = monotonic()
    while (elapsed_seconds := monotonic() - start_time) < DEPARTURE_ANIMATION_DURATION_SECONDS:
        travel_percent = elapsed_seconds / DEPARTURE_ANIMATION_DURATION_SECONDS
        convoy_x_pos = -convoy_width + int(travel_distance * travel_percent)

        canvas.Clear()
        for sprite, sprite_x_offset, sprite_height in zip(_CONVOY, sprite_x_offsets, sprite_heights):
            _draw_sprite(canvas, sprite, convoy_x_pos + sprite_x_offset, road_y_pos - sprite_height)
        canvas = matrix.SwapOnVSync(canvas)

        sleep(1 / _FRAMES_PER_SECOND)

    return canvas
