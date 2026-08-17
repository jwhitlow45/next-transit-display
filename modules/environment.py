# import env vars
import os
import re
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(".env")

LOG_LEVEL = os.getenv("LOG_LEVEL") or ""

# collect api keys defined as OPEN_DATA_511_API_KEY_<NUM> starting from 0, stopping at the first missing key
OPEN_DATA_511_API_KEY_LIST: list[str] = []
while api_key := os.getenv(f"OPEN_DATA_511_API_KEY_{len(OPEN_DATA_511_API_KEY_LIST)}"):
    OPEN_DATA_511_API_KEY_LIST.append(api_key)
if len(OPEN_DATA_511_API_KEY_LIST) == 0:
    raise ValueError(
        "Environment variable 'OPEN_DATA_511_API_KEY_0' must be set in .env file at project root"
    )
OPEN_DATA_511_AGENCY_ID = os.getenv("OPEN_DATA_511_AGENCY_ID") or ""
_OPEN_DATA_511_STOPCODES = os.getenv("OPEN_DATA_511_STOPCODES") or ""

LED_MATRIX_COLS = int(os.getenv("LED_MATRIX_COLS") or -1)
LED_MATRIX_ROWS = int(os.getenv("LED_MATRIX_ROWS") or -1)
LED_MATRIX_CHAIN_LENGTH = int(os.getenv("LED_MATRIX_CHAIN_LENGTH") or -1)
LED_MATRIX_PARALLEL = int(os.getenv("LED_MATRIX_PARALLEL") or -1)
LED_MATRIX_GPIO_SLOWDOWN = int(os.getenv("LED_MATRIX_GPIO_SLOWDOWN") or -1)
LED_MATRIX_HARDWARE_MAPPING = os.getenv("LED_MATRIX_HARDWARE_MAPPING") or ""
LED_MATRIX_MAX_BRIGHTNESS = int(os.getenv("LED_MATRIX_MAX_BRIGHTNESS") or -1)

REFRESH_API_INTERVAL_SECONDS = int(os.getenv("REFRESH_API_INTERVAL_SECONDS") or -1)
REFRESH_DISPLAY_INTERVAL_SECONDS = int(os.getenv("REFRESH_DISPLAY_INTERVAL_SECONDS") or -1)

_LINE_REFERENCES = os.getenv("LINE_REFERENCES") or ""
_LINE_STOPCODES = os.getenv("LINE_STOPCODES") or ""
_LINE_DISAMBIGUATION_SYMBOLS = os.getenv("LINE_DISAMBIGUATION_SYMBOLS") or ""

# process env vars
OPEN_DATA_511_STOPCODE_LIST = [stopcode for stopcode in _OPEN_DATA_511_STOPCODES.split(",") if stopcode]
if len(OPEN_DATA_511_STOPCODE_LIST) == 0:
    raise ValueError("Environment variable 'OPEN_DATA_511_STOPCODES' must be set in .env file at project root")

_LINE_REFERENCE_LIST = _LINE_REFERENCES.split(",")
_LINE_STOPCODE_LIST = _LINE_STOPCODES.split(",")
_LINE_DISAMBIGUATION_SYMBOL_LIST = _LINE_DISAMBIGUATION_SYMBOLS.split(",")
if not len(_LINE_REFERENCE_LIST) == len(_LINE_STOPCODE_LIST) == len(_LINE_DISAMBIGUATION_SYMBOL_LIST):
    raise ValueError(
        "Environment variables relating to line reference disambiguation must all have the same number of entries"
    )

LINE_DISAMBIGUATION_SYMBOL_DICT: dict[str, dict[str, str]] = defaultdict(dict)
for line_reference, stopcode, symbol in zip(
    _LINE_REFERENCE_LIST, _LINE_STOPCODE_LIST, _LINE_DISAMBIGUATION_SYMBOL_LIST
):
    LINE_DISAMBIGUATION_SYMBOL_DICT[stopcode][line_reference] = symbol

# optional departure animation directions aligned with the line disambiguation lists, valued as plain
# "R"/"L" strings rather than the AnimationDirection enum to avoid a circular import
_LINE_ANIMATION_DIRECTIONS = os.getenv("LINE_ANIMATION_DIRECTIONS") or ""
LINE_ANIMATION_DIRECTION_DICT: dict[str, dict[str, str]] = defaultdict(dict)
if _LINE_ANIMATION_DIRECTIONS:
    _LINE_ANIMATION_DIRECTION_LIST = _LINE_ANIMATION_DIRECTIONS.split(",")
    if len(_LINE_ANIMATION_DIRECTION_LIST) != len(_LINE_REFERENCE_LIST):
        raise ValueError(
            "Environment variable LINE_ANIMATION_DIRECTIONS must have the same number of entries as LINE_REFERENCES"
        )
    if any(direction not in ("R", "L") for direction in _LINE_ANIMATION_DIRECTION_LIST):
        raise ValueError("Environment variable LINE_ANIMATION_DIRECTIONS entries must be either 'R' or 'L'")
    for line_reference, stopcode, direction in zip(
        _LINE_REFERENCE_LIST, _LINE_STOPCODE_LIST, _LINE_ANIMATION_DIRECTION_LIST
    ):
        LINE_ANIMATION_DIRECTION_DICT[stopcode][line_reference] = direction

# optional per-line identifier colors aligned with the line disambiguation lists, valued as color names
# which are validated against the Colors class in display_utils to avoid a circular import here
_LINE_COLORS = os.getenv("LINE_COLORS") or ""
LINE_COLOR_DICT: dict[str, dict[str, str]] = defaultdict(dict)
if _LINE_COLORS:
    _LINE_COLOR_LIST = _LINE_COLORS.split(",")
    if len(_LINE_COLOR_LIST) != len(_LINE_REFERENCE_LIST):
        raise ValueError(
            "Environment variable LINE_COLORS must have the same number of entries as LINE_REFERENCES"
        )
    for line_reference, stopcode, color_name in zip(_LINE_REFERENCE_LIST, _LINE_STOPCODE_LIST, _LINE_COLOR_LIST):
        LINE_COLOR_DICT[stopcode][line_reference] = color_name

LINE_REFERENCE_ORDER = os.getenv("LINE_REFERENCE_ORDER") or ""
FUTURE_STOP_VISITS_SHOWN = int(os.getenv("FUTURE_STOP_VISITS_SHOWN") or -1)
ENABLE_DEPARTURE_ANIMATION = int(os.getenv("ENABLE_DEPARTURE_ANIMATION") or 1)
FONT = os.getenv("FONT") or ""
# FONT name should contain "<width>x<height>" (e.g. "5x7.bdf", "clR6x12.bdf") so this gets font width for alignment
_FONT_DIMENSIONS_MATCH = re.search(r"(\d+)x(\d+)", FONT)
if _FONT_DIMENSIONS_MATCH is None:
    raise ValueError(
        "Environment variable 'FONT' must be set to a font name containing '<width>x<height>' (e.g. '5x7.bdf'); "
        f"got '{FONT}'"
    )
FONT_WIDTH = int(_FONT_DIMENSIONS_MATCH.group(1))
FONT_COLOR = os.getenv("FONT_COLOR") or ""
FONT_ALIGNMENT = os.getenv("FONT_X_ALIGNMENT") or ""

# perceived brightness cap applied to every display color, 0 disables
COLOR_LUMINANCE_CAP = int(os.getenv("COLOR_LUMINANCE_CAP") or 0)
if not 0 <= COLOR_LUMINANCE_CAP <= 255:
    raise ValueError("Environment variable COLOR_LUMINANCE_CAP must be between 0 and 255")

# how the leading arrival time of a row pulses just before its departure animation plays; gentle defaults
# keep it noticeable without being distracting
PULSE_WINDOW_SECONDS = int(os.getenv("PULSE_WINDOW_SECONDS") or 5)
PULSE_FREQUENCY_HZ = float(os.getenv("PULSE_FREQUENCY_HZ") or 1.0)
PULSE_MIN_BRIGHTNESS_PERCENT = float(os.getenv("PULSE_MIN_BRIGHTNESS_PERCENT") or 0.4)
PULSE_FRAMES_PER_SECOND = int(os.getenv("PULSE_FRAMES_PER_SECOND") or 30)
if not 0 < PULSE_MIN_BRIGHTNESS_PERCENT <= 1:
    raise ValueError(
        "Environment variable PULSE_MIN_BRIGHTNESS_PERCENT must be above 0 (so lettering never goes blank) "
        "and at most 1"
    )

# a row's leading arrival time is colored by urgency when its displayed minutes-until-arrival is at or
# below these thresholds
ARRIVAL_RUN_MINUTES = int(os.getenv("ARRIVAL_RUN_MINUTES") or 1)
ARRIVAL_LEAVE_NOW_MINUTES = int(os.getenv("ARRIVAL_LEAVE_NOW_MINUTES") or 3)

ENABLE_SUN_BASED_BRIGHTNESS = int(os.getenv("ENABLE_SUN_BASED_BRIGHTNESS") or 0)
SUN_BASED_BRIGHTNESS_LAT = float(os.getenv("SUN_BASED_BRIGHTNESS_LAT") or -1)
SUN_BASED_BRIGHTNESS_LNG = float(os.getenv("SUN_BASED_BRIGHTNESS_LNG") or -1)
SUN_BASED_BRIGHTNESS_TZ = os.getenv("SUN_BASED_BRIGHTNESS_TZ") or ""
SUN_DAYLIGHT_OFFSET = int(os.getenv("SUN_DAYLIGHT_OFFSET") or 0)
LED_MATRIX_MIN_BRIGHTNESS = int(os.getenv("LED_MATRIX_MIN_BRIGHTNESS") or LED_MATRIX_MAX_BRIGHTNESS)

if ENABLE_SUN_BASED_BRIGHTNESS == 1:
    # NOTE: SUN_DAYLIGHT_OFFSET is not checked here as it defaults to 0
    if os.getenv("SUN_BASED_BRIGHTNESS_LAT") is None:
        raise ValueError(
            "Environment variable SUN_BASED_BRIGHTNESS_LAT is required when ENABLE_SUN_BASED_BRIGHTNESS is 1"
        )
    if os.getenv("SUN_BASED_BRIGHTNESS_LNG") is None:
        raise ValueError(
            "Environment variable SUN_BASED_BRIGHTNESS_LNG is required when ENABLE_SUN_BASED_BRIGHTNESS is 1"
        )
    if os.getenv("SUN_BASED_BRIGHTNESS_TZ") is None:
        raise ValueError(
            "Environment variable SUN_BASED_BRIGHTNESS_TZ is required when ENABLE_SUN_BASED_BRIGHTNESS is 1"
        )
    if os.getenv("LED_MATRIX_MIN_BRIGHTNESS") is None:
        raise ValueError(
            "Environment variable LED_MATRIX_MIN_BRIGHTNESS is required when ENABLE_SUN_BASED_BRIGHTNESS is 1"
        )
