# import env vars
import os
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(".env")

LOG_LEVEL = os.getenv("LOG_LEVEL") or ""

OPEN_DATA_511_API_KEY_0 = os.getenv("OPEN_DATA_511_API_KEY_0") or ""
OPEN_DATA_511_API_KEY_1 = os.getenv("OPEN_DATA_511_API_KEY_1") or ""
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
    open_data_stop_code_env_var_name = f"{_OPEN_DATA_511_STOPCODES=}".split("=")[0]
    raise ValueError(
        f"Environment variable '{open_data_stop_code_env_var_name}' must be set in .env file at project root"
    )

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

FUTURE_STOP_VISITS_SHOWN = int(os.getenv("FUTURE_STOP_VISITS_SHOWN") or -1)
FONT = os.getenv("FONT") or ""
# FONT should be string of "<width>x<height>.bdf" so this gets font width for alignment
FONT_WIDTH = int((FONT or "-1").split("x")[0])
FONT_COLOR = os.getenv("FONT_COLOR") or ""
FONT_ALIGNMENT = os.getenv("FONT_X_ALIGNMENT") or ""
