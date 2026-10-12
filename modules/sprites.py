from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from modules.display_utils import Colors, cap_if_enabled

_VEHICLE_GAP_PIXELS = 6
# one row of a 7 pixel tall font, see the NOTE above the sprites
_MAX_SPRITE_ROWS = 7


class AnimationDirection(StrEnum):
    LEFT_TO_RIGHT = "R"
    RIGHT_TO_LEFT = "L"


# "." pixels are transparent, every other character is drawn with its legend color. Colors entries are
# capped once when display_utils is imported, and capping a capped color again can shift a channel by one
# through rounding, so only the raw colors defined here go through cap_if_enabled
SPRITE_COLOR_LEGEND = {
    "R": Colors.RED,
    "S": Colors.SILVER,
    "Y": Colors.YELLOW,
    "G": Colors.GREEN,
    "C": Colors.CREAM,
    "B": Colors.BLUE,
    "K": Colors.GRAY,
    "D": cap_if_enabled((70, 70, 70)),  # dark window glass, not part of Colors as it is too dim for text
    "W": Colors.WHITE,
    # a deep orange keeps a pumpkin's yellow carved face looking lit from inside. COLOR_LUMINANCE_CAP pulls
    # yellow down to the brightness of brighter oranges, so only a dimmer orange stays darker than the face
    "O": Colors.MUNI_LESS,
    "P": Colors.PURPLE,
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

# halloween ghost bus: a white sheet in the shape of a bus with hollow windows, a wavy hem where its
# wheels should be, and an eerie green headlight
_GHOST_BUS_SPRITE = [
    "..WWWWWWWWWW..",
    ".WWWWWWWWWWWW.",
    ".W..W..W..W.W.",
    ".W..W..W..W.W.",
    ".WWWWWWWWWWWG.",
    ".WWWWWWWWWWWW.",
    ".W.WW.WW.WW.W.",
]

# halloween pumpkin coach: a jack-o'-lantern on wheels with a lit carved face and a green stem
_PUMPKIN_COACH_SPRITE = [
    ".......GG.......",
    "..OOOOOOOOOOOO..",
    ".OOOYYOOOOYYOOO.",
    ".OOOOOOOOOOOOOO.",
    ".OOYYOYYYYOYYOO.",
    "..OOOOOOOOOOOO..",
    "..KK........KK..",
]

# halloween hearse: purple, as black pixels are just unlit LEDs. hollow windows, a silver landau bar on
# the rear quarter, and a long hood out front
_HEARSE_SPRITE = [
    ".PPPPPPPPPPP......",
    ".PPP....P...PP....",
    ".PSP....P...PPP...",
    ".PPPPPPPPPPPPPPPP.",
    ".PPPPPPPPPPPPPPPY.",
    "..PPPPPPPPPPPPPP..",
    "...KK.......KK....",
]

# halloween bat: red eyes, bottom rows left transparent so it flies above the road line
_BAT_SPRITE = [
    "P..P.P..P",
    "PP.RPR.PP",
    "PPPPPPPPP",
    ".P..P..P.",
    ".........",
    ".........",
    ".........",
]

# these keys are the names DEPARTURE_ANIMATION_SPRITES and the convoy animation accept, keep ENVIRONMENT.md's
# list of valid sprite names in sync
SPRITES_BY_NAME = {
    "BUS": _BUS_SPRITE,
    "STREETCAR": _STREETCAR_SPRITE,
    "SUBWAY_CAR": _SUBWAY_CAR_SPRITE,
    "GHOST_BUS": _GHOST_BUS_SPRITE,
    "PUMPKIN_COACH": _PUMPKIN_COACH_SPRITE,
    "HEARSE": _HEARSE_SPRITE,
    "BAT": _BAT_SPRITE,
}


def validate_sprite(sprite_name: str, sprite: list[str]):
    """Raises a ValueError naming the sprite unless it can be drawn and mirrored safely

    Rows must share one width because mirroring reverses each row in place, and an unknown character would
    otherwise only fail mid-draw and take the display down with it
    """
    if not 0 < len(sprite) <= _MAX_SPRITE_ROWS:
        raise ValueError(f"Sprite {sprite_name} must have 1 to {_MAX_SPRITE_ROWS} rows, has {len(sprite)}")
    if len({len(row) for row in sprite}) != 1:
        raise ValueError(f"Sprite {sprite_name} rows must all be the same width")
    unknown_chars = {char for row in sprite for char in row if char != "." and char not in SPRITE_COLOR_LEGEND}
    if unknown_chars:
        raise ValueError(f"Sprite {sprite_name} uses characters missing from the legend: {sorted(unknown_chars)}")


for _sprite_name, _sprite in SPRITES_BY_NAME.items():
    validate_sprite(_sprite_name, _sprite)


@dataclass(frozen=True)
class Convoy:
    """A row of sprites laid out left to right as they appear on the display

    x_offsets are each sprite's left edge relative to the convoy's left edge, width spans every sprite and
    the gaps between them, and height is the tallest sprite
    """

    sprites: tuple[tuple[str, ...], ...]
    x_offsets: tuple[int, ...]
    width: int
    height: int


@cache  # convoys are rebuilt for every departure, and the inputs are a handful of fixed configurations
def build_convoy(sprite_names: tuple[str, ...], direction: AnimationDirection):
    """Lays out the named sprites as a convoy driving in the given direction, the first name leading

    Args:
        sprite_names (tuple[str, ...]): names from SPRITES_BY_NAME, leading sprite first, a tuple so it can be cached
        direction (AnimationDirection): the direction the convoy drives

    Returns:
        Convoy: the laid out convoy
    """
    # sprites are drawn facing right and drive left to right with the leading sprite rightmost
    sprites = [SPRITES_BY_NAME[sprite_name] for sprite_name in reversed(sprite_names)]
    if direction == AnimationDirection.RIGHT_TO_LEFT:
        # mirror the sprites and reverse their order so the leading sprite still leads when driving right to left
        sprites = [[row[::-1] for row in sprite] for sprite in reversed(sprites)]

    x_offsets: list[int] = []
    next_x_offset = 0
    for sprite in sprites:
        x_offsets.append(next_x_offset)
        next_x_offset += len(sprite[0]) + _VEHICLE_GAP_PIXELS
    return Convoy(
        sprites=tuple(tuple(sprite) for sprite in sprites),
        x_offsets=tuple(x_offsets),
        width=next_x_offset - _VEHICLE_GAP_PIXELS,
        height=max(len(sprite) for sprite in sprites),
    )


def draw_sprite(canvas, sprite, x_pos: int, y_pos: int):
    """Draws a sprite onto a canvas with its top-left corner at (x_pos, y_pos)

    Args:
        canvas: canvas to draw the sprite onto, out of bounds pixels are clipped by SetPixel
        sprite: rows of sprite characters, see SPRITE_COLOR_LEGEND
        x_pos (int): x position of the top-left corner of the sprite
        y_pos (int): y position of the top-left corner of the sprite
    """
    for y_offset, row in enumerate(sprite):
        for x_offset, char in enumerate(row):
            if char != ".":
                canvas.SetPixel(x_pos + x_offset, y_pos + y_offset, *SPRITE_COLOR_LEGEND[char])


def draw_convoy(canvas, convoy: Convoy, x_pos: int, road_y_pos: int):
    """Draws a convoy with its left edge at x_pos, every sprite resting on the road line just above road_y_pos

    Sprites share a road line rather than a top edge so every wheel touches the same row of pixels whatever
    each sprite's height
    """
    for sprite, sprite_x_offset in zip(convoy.sprites, convoy.x_offsets):
        draw_sprite(canvas, sprite, x_pos + sprite_x_offset, road_y_pos - len(sprite))
