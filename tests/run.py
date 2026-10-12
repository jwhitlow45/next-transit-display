"""Runs every test in this folder from a scratch directory with a fixed environment

modules/environment.py loads .env from the working directory at import, and modules/logger.py writes its log
file there too. Running from a scratch directory with every variable set here keeps a real .env and log file
out of the tests, so they behave the same on any machine. Run from the root of the repo:

    uv run python tests/run.py
"""

import json
import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)

# every variable the display reads, so nothing leaks in from the shell either. Optional ones are set empty
# to take their defaults
TEST_ENVIRONMENT = {
    # quiet, assertLogs still sees whatever a test asks for
    "LOG_LEVEL": "CRITICAL",
    "OPEN_DATA_511_API_KEY_0": "test-api-key",
    "OPEN_DATA_511_API_KEY_1": "",
    "OPEN_DATA_511_AGENCY_ID": "SF",
    "OPEN_DATA_511_STOPCODES": "13516",
    "LED_MATRIX_ROWS": "32",
    "LED_MATRIX_COLS": "64",
    "LED_MATRIX_CHAIN_LENGTH": "1",
    "LED_MATRIX_PARALLEL": "1",
    "LED_MATRIX_GPIO_SLOWDOWN": "10",
    "LED_MATRIX_HARDWARE_MAPPING": "regular",
    "LED_MATRIX_MAX_BRIGHTNESS": "100",
    "REFRESH_API_INTERVAL_SECONDS": "62",
    "REFRESH_DISPLAY_INTERVAL_SECONDS": "5",
    "LINE_REFERENCES": "",
    "LINE_STOPCODES": "",
    "LINE_DISAMBIGUATION_SYMBOLS": "",
    "LINE_ANIMATION_DIRECTIONS": "",
    "LINE_COLORS": "",
    "LINE_REFERENCE_ORDER": "LINE_REFERENCE",
    "FUTURE_STOP_VISITS_SHOWN": "2",
    "ENABLE_DEPARTURE_ANIMATION": "1",
    "DEPARTURE_ANIMATION_SPRITES": "",
    "PULSE_WINDOW_SECONDS": "",
    "PULSE_FREQUENCY_HZ": "",
    "PULSE_MIN_BRIGHTNESS_PERCENT": "",
    "PULSE_FRAMES_PER_SECOND": "",
    "ARRIVAL_RUN_MINUTES": "",
    "ARRIVAL_LEAVE_NOW_MINUTES": "",
    "ARRIVAL_RUN_COLOR": "",
    "ARRIVAL_LEAVE_NOW_COLOR": "",
    "FONT": "5x7.bdf",
    "FONT_COLOR": "MUNI",
    "FONT_X_ALIGNMENT": "CENTER",
    "COLOR_LUMINANCE_CAP": "",
    "ENABLE_SUN_BASED_BRIGHTNESS": "0",
    "SUN_BASED_BRIGHTNESS_LAT": "",
    "SUN_BASED_BRIGHTNESS_LNG": "",
    "SUN_BASED_BRIGHTNESS_TZ": "",
    "SUN_DAYLIGHT_OFFSET": "",
    "LED_MATRIX_MIN_BRIGHTNESS": "",
    "ENABLE_ANIMATION_LISTENER": "0",
    "ANIMATION_MQTT_HOST": "",
    "ANIMATION_MQTT_PORT": "",
    "ANIMATION_MQTT_USERNAME": "",
    "ANIMATION_MQTT_PASSWORD": "",
}


def main():
    with tempfile.TemporaryDirectory() as scratch_dir:
        os.chdir(scratch_dir)
        # the emulator reads its config from the working directory and otherwise logs a traceback for every
        # display adapter this machine can't load, burying the test output
        with open("emulator_config.json", "w") as config_file:
            json.dump({"suppress_adapter_load_errors": True}, config_file)

        # must happen before anything imports modules.environment
        os.environ.update(TEST_ENVIRONMENT)
        sys.path[:0] = [REPO_DIR, TESTS_DIR]

        suite = unittest.defaultTestLoader.discover(TESTS_DIR, top_level_dir=TESTS_DIR)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
