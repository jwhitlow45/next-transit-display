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
from models.SunriseSunset import SunriseSunsetResult
from modules.departure_animation import play_departure_animation
from modules.display_utils import (
    Colors,
    FontAlignment,
    LineReferenceOrder,
    calculate_display_brightness,
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
from services.SunriseSunset import SunriseSunsetClient

RGBMatrix, _, graphics = get_rgb_matrix_imports()

# define globally so it is available to both threads
display_info_dict: dict[str, DisplayInfoModel] | None = None
display_info_lock = threading.Lock()

sunrise_sunset_result: SunriseSunsetResult | None = None
sunrise_sunset_result_lock = threading.Lock()


def main():
    # daemon threads so the process can exit on Ctrl+C/SIGTERM instead of hanging on the while True loops
    threads = [
        threading.Thread(target=display_loop, daemon=True),
        threading.Thread(target=api_loop, daemon=True),
    ]
    [thread.start() for thread in threads]

    # will never end as threads are while True loops, but waiting for their completion keeps the program running
    [thread.join() for thread in threads]


def stop_visit_sort_key(stop_visit: StopVisitModel):
    arrival_time = (
        stop_visit.expected_arrival_time
        if stop_visit.expected_arrival_time is not None
        # infinity time should not have a timezone, fuck you Guido van Rossum
        else datetime.max.replace(tzinfo=ZoneInfo("UTC"))
    )
    # keys must have the same shape for every visit or sorted() raises TypeError on tuple-vs-datetime comparison
    if env.LINE_REFERENCE_ORDER == LineReferenceOrder.ARRIVAL_TIME:
        return ("", arrival_time)
    return (stop_visit.line_reference, arrival_time)


def display_loop():
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
        try:
            # soonest arrival time shown on the display and the per-row times/draw args behind it,
            # used to time the departure animation and target it at the arriving line's row
            next_arrival_time: datetime | None = None
            display_line_arrival_times: list[list[datetime]] = []
            graphics_display_line_args = []

            # snapshot the dict reference so drawing doesn't block api_loop; safe because api_loop
            # always replaces the dict rather than mutating it in place
            with display_info_lock:
                display_info_snapshot = display_info_dict

            if display_info_snapshot is not None and len(display_info_snapshot) > 0:
                now = datetime.now(timezone.utc)
                display_lines: list[str] = []

                for stopcode, display_info_model in display_info_snapshot.items():
                    sorted_stop_visit_list = sorted(display_info_model.stop_visit_list, key=stop_visit_sort_key)

                    # group by line reference, with each list ordered by expected arrival time
                    line_reference_list_map: dict[str, list[StopVisitModel]] = defaultdict(list)
                    for stop_visit in sorted_stop_visit_list:
                        # only display if arriving in future
                        if (
                            stop_visit.expected_arrival_time is not None
                            and stop_visit.expected_arrival_time > now
                            and len(line_reference_list_map[stop_visit.line_reference])
                            < env.FUTURE_STOP_VISITS_SHOWN
                        ):
                            line_reference_list_map[stop_visit.line_reference].append(stop_visit)

                    # lines configured in LINE_REFERENCES/LINE_STOPCODES are always shown, even when they
                    # currently have no upcoming arrivals
                    for line_reference in env.LINE_DISAMBIGUATION_SYMBOL_DICT.get(stopcode, {}):
                        if line_reference not in line_reference_list_map:
                            line_reference_list_map[line_reference] = []

                    # insertion order comes from the visit sort, which lines without arrivals aren't part of,
                    # so re-sort for a deterministic row order (arrival time mode leaves them last instead)
                    line_reference_row_order = list(line_reference_list_map)
                    if env.LINE_REFERENCE_ORDER != LineReferenceOrder.ARRIVAL_TIME:
                        line_reference_row_order.sort()

                    for line_reference in line_reference_row_order:
                        line_arrival_times = [
                            sv.expected_arrival_time
                            for sv in line_reference_list_map[line_reference]
                            if sv.expected_arrival_time is not None
                        ]
                        display_lines.append(
                            generate_display_line_row(
                                line_reference,
                                env.LINE_DISAMBIGUATION_SYMBOL_DICT.get(stopcode, {}).get(line_reference, ""),
                                line_arrival_times,
                                now,
                            )
                        )
                        display_line_arrival_times.append(line_arrival_times)

                # cap rows to what fits on the panel, extra rows would draw off-screen
                max_display_lines = (env.LED_MATRIX_ROWS - 1) // font.height
                display_lines = display_lines[:max_display_lines]
                display_line_arrival_times = display_line_arrival_times[:max_display_lines]

                # only arrival times that made it onto the panel should be able to trigger the departure
                # animation; when the animation is disabled next_arrival_time stays None so the display
                # never wakes early and never plays it
                if env.ENABLE_DEPARTURE_ANIMATION == 1:
                    next_arrival_time = min(
                        (arrival_time for row_times in display_line_arrival_times for arrival_time in row_times),
                        default=None,
                    )

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
                    [display_info.response_timestamp for display_info in display_info_snapshot.values()]
                )
                logger.debug(f"oldest_response_timestamp: {oldest_response_timestamp}")
                logger.debug(display_info_snapshot)
                status_led_colors = get_status_led_colors(
                    oldest_response_timestamp, env.REFRESH_API_INTERVAL_SECONDS
                )
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

            # dynamically calculate display brightness if enabled and data is available
            if env.ENABLE_SUN_BASED_BRIGHTNESS == 1:
                with sunrise_sunset_result_lock:
                    sunrise_sunset_snapshot = sunrise_sunset_result
                if sunrise_sunset_snapshot is not None:
                    brightness = calculate_display_brightness(
                        sunrise_sunset_result=sunrise_sunset_snapshot,
                        min_brightness=env.LED_MATRIX_MIN_BRIGHTNESS,
                        max_brightness=env.LED_MATRIX_MAX_BRIGHTNESS,
                    )
                    logger.debug(f"display brightness: {brightness}")
                    logger.debug(f"sunrise sunset result: {sunrise_sunset_snapshot}")
                    canvas.brightness = brightness

            canvas = matrix.SwapOnVSync(
                canvas
            )  # draw canvas, set returned canvas as new canvas to prevent flickering

            # wake at the next display refresh or when the soonest displayed arrival hits 0, whichever is sooner
            sleep_seconds = float(env.REFRESH_DISPLAY_INTERVAL_SECONDS)
            if next_arrival_time is not None:
                seconds_until_arrival = (next_arrival_time - datetime.now(timezone.utc)).total_seconds()
                sleep_seconds = min(sleep_seconds, max(seconds_until_arrival, 0))
            sleep(sleep_seconds)

            # an arrival time just hit 0, celebrate its departure before it disappears from its display row
            if next_arrival_time is not None and datetime.now(timezone.utc) >= next_arrival_time:
                animated_row_index_list = [
                    idx for idx, row_times in enumerate(display_line_arrival_times) if next_arrival_time in row_times
                ]
                background_display_line_args = [
                    args for idx, args in enumerate(graphics_display_line_args) if idx not in animated_row_index_list
                ]

                # re-draw every row except the animated ones (plus the status LED) behind the convoy each frame
                def draw_animation_background(animation_canvas):
                    for args in background_display_line_args:
                        graphics.DrawText(animation_canvas, font, *args)
                    animation_canvas.SetPixel(*status_led_xy, *status_led_colors)

                # rows are drawn with their baseline at 1 + (font.height * (idx + 1)), so the top of a
                # row's band of pixels sits a full font height above that, just below the baseline above it
                animation_row_y_pos_list = [2 + (font.height * idx) for idx in animated_row_index_list]
                canvas = play_departure_animation(
                    matrix,
                    canvas,
                    env.LED_MATRIX_COLS,
                    animation_row_y_pos_list,
                    font.height,
                    draw_animation_background,
                )
        except Exception:
            logger.error("Unexpected exception while trying to display stop data...terminating program", exc_info=True)
            os._exit(1)


def api_loop():
    global display_info_dict, sunrise_sunset_result

    client_list = [OpenData511Client(api_key) for api_key in env.OPEN_DATA_511_API_KEY_LIST]

    client_idx = 0

    sunrise_sunset_client: SunriseSunsetClient | None = None
    if env.ENABLE_SUN_BASED_BRIGHTNESS == 1:
        sunrise_sunset_client = SunriseSunsetClient()

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
                # fail program on 401; an unhandled raise would only kill this thread and leave the display
                # running with stale data forever
                if err.response.status_code == 401:
                    logger.error(f"API key rejected for stopcode {stopcode}: 401 {err.response.text}")
                    os._exit(1)
                logger.error(
                    f"API Request Failed for stopcode {stopcode}: {err.response.status_code} {err.response.text}"
                )
            except Exception:
                # catch all other errors as the OpenData511 API is fickle and I don't wanna play error whack-a-mole
                logger.error("Unexpected exception while trying to fetch stop data...continuing", exc_info=True)

        with display_info_lock:
            # NOTE: only want to overwrite stops for data we have fetched in case one of the API requests fails
            # This makes the display fault tolerant to occasional API request failures
            display_info_dict = (display_info_dict or {}) | display_info_dict_staged

        if sunrise_sunset_client is not None:
            now = datetime.now(ZoneInfo(env.SUN_BASED_BRIGHTNESS_TZ))
            # if result is not set or the sunrise data is for another date, refresh the data
            # in effect, the sunrise_sunset_result is only refreshed once per day to get data for that day
            if sunrise_sunset_result is None or sunrise_sunset_result.sunrise.date() != now.date():
                try:
                    response = sunrise_sunset_client.get_solar_time_data(
                        lat=env.SUN_BASED_BRIGHTNESS_LAT,
                        lng=env.SUN_BASED_BRIGHTNESS_LNG,
                        tzid=env.SUN_BASED_BRIGHTNESS_TZ,
                    )
                    with sunrise_sunset_result_lock:
                        sunrise_sunset_result = response.results
                except HTTPStatusError as err:
                    logger.error(
                        f"API Request Failed for SunriseSunset API: {err.response.status_code} {err.response.text}"
                    )
                except Exception:
                    logger.error(
                        "Unexpected exception while trying to fetch sunrise sunset data...continuing", exc_info=True
                    )

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
    except KeyboardInterrupt:
        pass  # daemon worker threads die with the process
    except Exception:
        logger.exception("Uncaught exception terminated program", exc_info=True)
        os._exit(1)
