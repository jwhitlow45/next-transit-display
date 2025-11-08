import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from os import path
from time import sleep
from zoneinfo import ZoneInfo

from httpx import HTTPStatusError

import modules.environment as env
from models.DisplayInfo import DisplayInfoModel, StopVisitModel
from modules.display_utils import (
    Colors,
    FontAlignment,
    LineReferenceOrder,
    generate_display_line_row,
    get_status_led_colors,
    get_text_center_x_pos,
    get_text_center_y_pos,
    get_text_x_pos,
)
from modules.logger import logger
from modules.rgbmatrix_configurer import get_rgb_matrix
from modules.rgbmatrix_importer import get_rgb_matrix_imports
from services.OpenData511 import OpenData511Client

RGBMatrix, _, graphics = get_rgb_matrix_imports()

# define globally so it is available to both threads
display_info_dict: dict[str, DisplayInfoModel] | None = None
display_info_lock = threading.Lock()


def main():
    threads = [threading.Thread(target=display_loop), threading.Thread(target=api_loop)]
    [thread.start() for thread in threads]

    # will never end as threads are while True loops, but waiting for their completion keeps the program running
    [thread.join() for thread in threads]


def display_loop():
    global display_info_dict

    # use bottom-right corner of display for status LED
    status_led_xy = (env.LED_MATRIX_COLS - 1, env.LED_MATRIX_ROWS - 1)

    # setup font
    font = graphics.Font()
    font.LoadFont(path.join("fonts", env.FONT))
    font_color = graphics.Color(*getattr(Colors, env.FONT_COLOR))

    # setup matrix and canvas for drawing to display
    matrix = get_rgb_matrix(
        cols=env.LED_MATRIX_COLS,
        rows=env.LED_MATRIX_ROWS,
        chain_length=env.LED_MATRIX_CHAIN_LENGTH,
        parallel=env.LED_MATRIX_PARALLEL,
        gpio_slowdown=env.LED_MATRIX_GPIO_SLOWDOWN,
        hardware_mapping=env.LED_MATRIX_HARDWARE_MAPPING,
        matrix_brightness=env.LED_MATRIX_MAX_BRIGHTNESS,
    )
    canvas = matrix.CreateFrameCanvas()

    while True:
        with display_info_lock:
            if display_info_dict is not None:
                now = datetime.now(timezone.utc)
                display_lines: list[str] = []

                for stopcode, display_info_model in display_info_dict.items():
                    sorted_stop_visit_list = sorted(
                        display_info_model.stop_visit_list,
                        key=lambda stop: (
                            stop.expected_arrival_time
                            if env.LINE_REFERENCE_ORDER == LineReferenceOrder.ARRIVAL_TIME
                            else (stop.line_reference, stop.expected_arrival_time)
                        )
                        if stop.expected_arrival_time is not None
                        else datetime.max.replace(
                            tzinfo=ZoneInfo("UTC")
                        ),  # infinity time should not have a timezone, fuck you Guido van Rossum
                    )

                    # group by line reference, with each list ordered by expected arrival time
                    line_reference_list_map: dict[str, list[StopVisitModel]] = defaultdict(list)
                    for stop_visit in sorted_stop_visit_list:
                        # only display if arriving in future
                        if (
                            stop_visit.expected_arrival_time is not None
                            and stop_visit.expected_arrival_time > now
                            and len(line_reference_list_map[stop_visit.line_reference]) < env.FUTURE_STOP_VISITS_SHOWN
                        ):
                            line_reference_list_map[stop_visit.line_reference].append(stop_visit)

                    for line_reference, stop_visit_list in line_reference_list_map.items():
                        display_lines.append(
                            generate_display_line_row(
                                line_reference,
                                env.LINE_DISAMBIGUATION_SYMBOL_DICT.get(stopcode, {}).get(line_reference, ""),
                                [
                                    sv.expected_arrival_time
                                    for sv in stop_visit_list
                                    if sv.expected_arrival_time is not None
                                ],
                                now,
                            )
                        )

                graphics_display_line_args = []
                for idx, display_line in enumerate(display_lines):
                    graphics_display_line_args.append(
                        (
                            get_text_x_pos(
                                display_line, env.FONT_WIDTH, env.LED_MATRIX_COLS, FontAlignment(env.FONT_ALIGNMENT)
                            ),
                            1 + ((font.height) * (idx + 1)),
                            font_color,
                            display_line,
                        )
                    )

                # LED in bottom right corner of display that acts as a visual indicator for how up-to-date the display
                # info is. Use oldest response timestamp to keep this simple
                oldest_response_timestamp = min(
                    [display_info.response_timestamp for display_info in display_info_dict.values()]
                )
                logger.debug(f"oldest_response_timestamp: {oldest_response_timestamp}")
                logger.debug(display_info_dict)
                status_led_colors = get_status_led_colors(oldest_response_timestamp, env.REFRESH_API_INTERVAL_SECONDS)
                # do all drawing as close as possible to canvas clear to prevent flickering
                canvas.Clear()
                for idx, args in enumerate(graphics_display_line_args):
                    graphics.DrawText(
                        canvas,
                        font,
                        *args,
                    )
                canvas.SetPixel(
                    *status_led_xy,
                    *status_led_colors,
                )
            else:
                loading_text = "Loading..."
                text_x_pos = get_text_center_x_pos(loading_text, env.FONT_WIDTH, env.LED_MATRIX_COLS)
                text_y_pos = get_text_center_y_pos(font.height, env.LED_MATRIX_ROWS)

                canvas.Clear()
                graphics.DrawText(
                    canvas,
                    font,
                    text_x_pos,
                    text_y_pos,
                    font_color,
                    loading_text,
                )

            canvas = matrix.SwapOnVSync(canvas)  # draw canvas, set returned canvas as new canvas to prevent flickering

        sleep(env.REFRESH_DISPLAY_INTERVAL_SECONDS)


def api_loop():
    global display_info_dict

    client_list = [OpenData511Client(env.OPEN_DATA_511_API_KEY_0)]
    if env.OPEN_DATA_511_API_KEY_1:
        client_list.append(OpenData511Client(env.OPEN_DATA_511_API_KEY_1))

    client_idx = 0

    while True:
        # utilizing a dict to isolate each stopcode so that request failures only impact the given requested stop
        # and not all data for all stops
        display_info_dict_staged: dict[str, DisplayInfoModel] = {}

        for stopcode in env.OPEN_DATA_511_STOPCODE_LIST:
            try:
                display_info_dict_staged[stopcode] = (
                    client_list[client_idx]
                    .get_transit_stop_monitoring(env.OPEN_DATA_511_AGENCY_ID, stopcode)
                    .convert_to_display_info()
                )
            except HTTPStatusError as err:
                # fail program on 401
                if err.response.status_code == 401:
                    raise err
                logger.error(
                    f"API Request Failed for stopcode {stopcode}: {err.response.status_code} {err.response.text}\n{err.response.json()}"
                )
            except Exception:
                # catch all other errors as the OpenData511 API is fickle and I don't wanna play error whack-a-mole
                logger.error("Unexpected exception while trying to fetch stop data...continuing", exc_info=True)

        with display_info_lock:
            # NOTE: only want to overwrite stops for data we have fetched in case one of the API requests fails
            # This makes the display fault tolerant to occasional API request failures
            display_info_dict = (display_info_dict or {}) | display_info_dict_staged

        # round-robin api requests across clients to spread api usage across api keys
        # this could be done smarter to avoid detection of single client using multiple api keys, but since opendata511
        # won't respond to my rate limit increase request I doubt they'll catch this
        client_idx += 1
        if client_idx >= len(client_list):
            client_idx = 0

        sleep(env.REFRESH_API_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Uncaught exception terminated program", exc_info=True)
        os._exit(1)
