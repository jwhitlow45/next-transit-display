import math
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from os import path
from time import monotonic, sleep
from zoneinfo import ZoneInfo

from httpx import HTTPStatusError

import modules.environment as env
from models.DisplayInfo import DisplayInfoModel, StopVisitModel
from models.SunriseSunset import SunriseSunsetResult
from modules.departure_animation import (
    DEPARTURE_ANIMATION_DURATION_SECONDS,
    AnimationDirection,
    DepartureAnimationRow,
    play_departure_animation,
    play_loading_animation,
)
from modules.display_utils import (
    Colors,
    FontAlignment,
    LineReferenceOrder,
    calculate_display_brightness,
    generate_display_line_row,
    get_status_led_colors,
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


def group_stop_visits_by_line(stopcode: str, stop_visit_list: list[StopVisitModel], now: datetime):
    """Groups a stop's future visits by line reference, in the order the lines should be displayed

    All future visits are kept, beyond just those displayed, so the departure animation can backfill
    arrival times as displayed ones depart
    """
    # group by line reference, with each list ordered by expected arrival time
    line_reference_list_map: dict[str, list[StopVisitModel]] = defaultdict(list)
    for stop_visit in sorted(stop_visit_list, key=stop_visit_sort_key):
        # only keep visits arriving in the future
        if stop_visit.expected_arrival_time is not None and stop_visit.expected_arrival_time > now:
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

    return {line_reference: line_reference_list_map[line_reference] for line_reference in line_reference_row_order}


def build_display_rows(display_info_snapshot: dict[str, DisplayInfoModel], now: datetime, max_row_count: int):
    """Builds the text, upcoming arrival times, animation direction, and identifier color of each display row

    Each row's arrival times list holds all upcoming arrivals, not just the FUTURE_STOP_VISITS_SHOWN
    displayed in the row text, so the departure animation can tow in backfill times as arrivals depart
    """
    display_lines: list[str] = []
    display_line_arrival_times: list[list[datetime]] = []
    display_line_animation_directions: list[AnimationDirection] = []
    display_line_colors: list[tuple[int, int, int]] = []
    display_line_keys: list[tuple[str, str]] = []

    for stopcode, display_info_model in display_info_snapshot.items():
        line_reference_list_map = group_stop_visits_by_line(stopcode, display_info_model.stop_visit_list, now)
        for line_reference, stop_visit_list in line_reference_list_map.items():
            line_arrival_times = [
                sv.expected_arrival_time for sv in stop_visit_list if sv.expected_arrival_time is not None
            ]
            display_lines.append(
                generate_display_line_row(
                    line_reference,
                    env.LINE_DISAMBIGUATION_SYMBOL_DICT.get(stopcode, {}).get(line_reference, ""),
                    line_arrival_times[: env.FUTURE_STOP_VISITS_SHOWN],
                    now,
                )
            )
            display_line_arrival_times.append(line_arrival_times)
            display_line_animation_directions.append(
                AnimationDirection(
                    env.LINE_ANIMATION_DIRECTION_DICT.get(stopcode, {}).get(
                        line_reference, AnimationDirection.LEFT_TO_RIGHT
                    )
                )
            )
            display_line_colors.append(
                getattr(Colors, env.LINE_COLOR_DICT.get(stopcode, {}).get(line_reference, env.FONT_COLOR))
            )
            display_line_keys.append((stopcode, line_reference))

    # cap rows to what fits on the panel, extra rows would draw off-screen
    return (
        display_lines[:max_row_count],
        display_line_arrival_times[:max_row_count],
        display_line_animation_directions[:max_row_count],
        display_line_colors[:max_row_count],
        display_line_keys[:max_row_count],
    )


def get_row_draw_segments(
    display_line: str,
    row_times: list[datetime],
    identifier_rgb: tuple[int, int, int],
    row_y_pos: int,
    now: datetime,
):
    """Calculates the positioned (x, y, rgb, text) DrawText segments of a single display row

    Rows are split into an identifier segment and one segment per arrival time so each can be colored
    independently: identifiers in their line's configured color, the leading arrival time by urgency,
    and far-off :( times faintly
    """
    baseline_rgb = getattr(Colors, env.FONT_COLOR)
    run_rgb = getattr(Colors, env.ARRIVAL_RUN_COLOR)
    leave_now_rgb = getattr(Colors, env.ARRIVAL_LEAVE_NOW_COLOR)

    row_x_pos = get_text_x_pos(display_line, env.FONT_WIDTH, env.LED_MATRIX_COLS, FontAlignment(env.FONT_ALIGNMENT))

    # the times block sits at the end of the row text, each time taking 2 characters plus a space
    times_char_index = len(display_line) - (3 * len(row_times) - 1) if row_times else len(display_line)
    row_segments: list[tuple[int, int, tuple[int, int, int], str]] = [
        (
            row_x_pos,
            row_y_pos,
            identifier_rgb,
            display_line[:times_char_index],
        )
    ]
    for time_idx, arrival_time in enumerate(row_times):
        time_char_index = times_char_index + 3 * time_idx
        time_text = display_line[time_char_index : time_char_index + 2]
        minutes_until_arrival = int((arrival_time - now).total_seconds() // 60)
        if time_text == ":(":
            time_rgb = Colors.MUNI_FAINT  # so far away there is no need to shout about it
        elif time_idx == 0 and minutes_until_arrival <= env.ARRIVAL_RUN_MINUTES:
            time_rgb = run_rgb  # arriving now, run
        elif time_idx == 0 and minutes_until_arrival <= env.ARRIVAL_LEAVE_NOW_MINUTES:
            time_rgb = leave_now_rgb  # arriving soon, leave now
        else:
            time_rgb = baseline_rgb
        row_segments.append((row_x_pos + time_char_index * env.FONT_WIDTH, row_y_pos, time_rgb, time_text))
    return row_segments


def get_display_line_draw_args(
    display_lines: list[str],
    display_line_arrival_times: list[list[datetime]],
    display_line_colors: list[tuple[int, int, int]],
    font,
    now: datetime,
):
    """Calculates the positioned (x, y, rgb, text) DrawText segments of each display row"""
    return [
        get_row_draw_segments(
            display_line,
            # only the displayed subset of each row's arrival times has segments in the row text
            display_line_arrival_times[idx][: env.FUTURE_STOP_VISITS_SHOWN],
            display_line_colors[idx],
            1 + (font.height * (idx + 1)),
            now,
        )
        for idx, display_line in enumerate(display_lines)
    ]


def draw_display_frame(canvas, font, graphics_display_line_args, status_led_xy, status_led_colors):
    """Draws the display row segments and status LED onto the canvas"""
    # do all drawing as close as possible to canvas clear to prevent flickering
    canvas.Clear()
    for row_segments in graphics_display_line_args:
        for x_pos, y_pos, rgb, text in row_segments:
            graphics.DrawText(canvas, font, x_pos, y_pos, graphics.Color(*rgb), text)
    canvas.SetPixel(*status_led_xy, *status_led_colors)


def apply_sun_based_brightness(canvas):
    """Sets the canvas brightness from the day's sunrise/sunset data when sun-based brightness is enabled"""
    if env.ENABLE_SUN_BASED_BRIGHTNESS != 1:
        return
    with sunrise_sunset_result_lock:
        sunrise_sunset_snapshot = sunrise_sunset_result
    if sunrise_sunset_snapshot is None:
        return

    brightness = calculate_display_brightness(
        sunrise_sunset_result=sunrise_sunset_snapshot,
        min_brightness=env.LED_MATRIX_MIN_BRIGHTNESS,
        max_brightness=env.LED_MATRIX_MAX_BRIGHTNESS,
    )
    logger.debug(f"display brightness: {brightness}")
    logger.debug(f"sunrise sunset result: {sunrise_sunset_snapshot}")
    canvas.brightness = brightness


def sleep_until_next_frame(next_arrival_time: datetime | None):
    """Sleeps until the next display refresh or until the soonest displayed arrival is about to hit 0,
    whichever is sooner, waking early enough to pulse the arrival time before its departure animation"""
    sleep_seconds = float(env.REFRESH_DISPLAY_INTERVAL_SECONDS)
    if next_arrival_time is not None:
        seconds_until_pulse_window = (
            next_arrival_time - datetime.now(timezone.utc)
        ).total_seconds() - env.PULSE_WINDOW_SECONDS
        sleep_seconds = min(sleep_seconds, max(seconds_until_pulse_window, 0))
    sleep(sleep_seconds)


def pulse_imminent_arrivals(
    matrix,
    canvas,
    font,
    next_arrival_time: datetime | None,
    display_line_arrival_times: list[list[datetime]],
    graphics_display_line_args,
    status_led_xy,
    status_led_colors,
):
    """Gently pulses the leading arrival time of rows seconds away from departure, until the soonest is due"""
    if next_arrival_time is None:
        return canvas
    now = datetime.now(timezone.utc)
    if (next_arrival_time - now).total_seconds() > env.PULSE_WINDOW_SECONDS:
        return canvas

    # the leading arrival time is the segment right after the row's identifier segment
    pulse_segments = []
    for idx, row_times in enumerate(display_line_arrival_times):
        if row_times and (min(row_times) - now).total_seconds() <= env.PULSE_WINDOW_SECONDS:
            pulse_segments.append(graphics_display_line_args[idx][1])

    start_time = monotonic()
    while (next_arrival_time - datetime.now(timezone.utc)).total_seconds() > 0:
        # cosine so the pulse starts from full brightness, with a floor so the lettering never goes blank
        pulse_phase = math.cos(2 * math.pi * env.PULSE_FREQUENCY_HZ * (monotonic() - start_time))
        brightness_percent = env.PULSE_MIN_BRIGHTNESS_PERCENT + (1 - env.PULSE_MIN_BRIGHTNESS_PERCENT) * (
            0.5 + 0.5 * pulse_phase
        )

        # re-draw the normal frame and overdraw each pulsing arrival time in a dimmed copy of its own color
        draw_display_frame(canvas, font, graphics_display_line_args, status_led_xy, status_led_colors)
        for x_pos, y_pos, rgb, text in pulse_segments:
            pulse_color = graphics.Color(*(int(channel * brightness_percent) for channel in rgb))
            graphics.DrawText(canvas, font, x_pos, y_pos, pulse_color, text)
        canvas = matrix.SwapOnVSync(canvas)

        sleep(1 / env.PULSE_FRAMES_PER_SECOND)
    return canvas


def play_departure_animation_for_due_arrivals(
    matrix,
    canvas,
    font,
    next_arrival_time: datetime | None,
    display_line_arrival_times: list[list[datetime]],
    display_line_keys: list[tuple[str, str]],
    display_line_animation_directions: list[AnimationDirection],
    graphics_display_line_args,
    status_led_xy,
    status_led_colors,
):
    """Plays the departure animation through the rows of any arrivals hitting 0, returning the current canvas"""
    if next_arrival_time is None or datetime.now(timezone.utc) < next_arrival_time:
        return canvas

    # one or more arrival times are hitting 0, celebrate the departures before they disappear from
    # their display rows; every arrival due before this animation pass finishes shares it so that
    # back-to-back departures are neither skipped over nor animated twice
    now = datetime.now(timezone.utc)
    animation_end_time = now + timedelta(seconds=DEPARTURE_ANIMATION_DURATION_SECONDS)
    animated_row_index_list = [
        idx
        for idx, row_times in enumerate(display_line_arrival_times)
        if any(arrival_time <= animation_end_time for arrival_time in row_times)
    ]
    background_display_line_args = [
        args for idx, args in enumerate(graphics_display_line_args) if idx not in animated_row_index_list
    ]

    # re-draw every row except the animated ones (plus the status LED) behind the convoy each frame
    def draw_animation_background(animation_canvas):
        for row_segments in background_display_line_args:
            for x_pos, y_pos, rgb, text in row_segments:
                graphics.DrawText(animation_canvas, font, x_pos, y_pos, graphics.Color(*rgb), text)
        animation_canvas.SetPixel(*status_led_xy, *status_led_colors)

    # animated rows draw their segments at a brightness and x offset so they can fade out and be towed in
    def draw_animation_segments(animation_canvas, segments, brightness_percent, x_offset):
        for x_pos, y_pos, rgb, text in segments:
            dimmed_color = graphics.Color(*(int(channel * brightness_percent) for channel in rgb))
            graphics.DrawText(animation_canvas, font, x_pos + x_offset, y_pos, dimmed_color, text)

    # tow in times from the freshest fetched data so any predictions fetched since the last display
    # render are included, since the API only ever publishes a few predictions per line
    with display_info_lock:
        display_info_snapshot = display_info_dict

    animation_row_list = []
    for idx in animated_row_index_list:
        old_segments = graphics_display_line_args[idx]
        _, row_baseline_y_pos, identifier_rgb, identifier_text = old_segments[0]

        # rebuild the row as it will look once the departed arrivals are removed so the convoy can tow
        # it into place, backfilling from upcoming arrivals beyond those displayed when available
        stopcode, line_reference = display_line_keys[idx]
        upcoming_times = display_line_arrival_times[idx]
        if display_info_snapshot is not None and stopcode in display_info_snapshot:
            fresh_stop_visits = group_stop_visits_by_line(
                stopcode, display_info_snapshot[stopcode].stop_visit_list, now
            ).get(line_reference, [])
            upcoming_times = [
                stop_visit.expected_arrival_time
                for stop_visit in fresh_stop_visits
                if stop_visit.expected_arrival_time is not None
            ]
        remaining_times = [
            arrival_time for arrival_time in upcoming_times if arrival_time > animation_end_time
        ][: env.FUTURE_STOP_VISITS_SHOWN]
        # the identifier segment already holds the formatted reference and symbol, ending with the
        # separator space when times followed it; re-generating with it re-formats the times fresh
        identifier_reference = identifier_text[:-1] if identifier_text.endswith(" ") else identifier_text
        towed_display_line = generate_display_line_row(identifier_reference, "", remaining_times, now)
        towed_segments = get_row_draw_segments(
            towed_display_line,
            remaining_times,
            identifier_rgb,
            row_baseline_y_pos,
            now,
        )

        animation_row_list.append(
            DepartureAnimationRow(
                # rows are drawn with their baseline at 1 + (font.height * (idx + 1)), so the top of a
                # row's band of pixels sits a full font height above that, just below the baseline above it
                row_y_pos=row_baseline_y_pos - font.height + 1,
                direction=display_line_animation_directions[idx],
                fading_segments=old_segments,
                towed_segments=towed_segments,
                towed_left_x=min(segment[0] for segment in towed_segments),
                towed_right_x=max(segment[0] + (len(segment[3]) * env.FONT_WIDTH) for segment in towed_segments),
            )
        )

    return play_departure_animation(
        matrix,
        canvas,
        env.LED_MATRIX_COLS,
        animation_row_list,
        font.height,
        draw_animation_background,
        draw_animation_segments,
    )


def display_loop():
    # use bottom-right corner of display for status LED
    status_led_xy = (env.LED_MATRIX_COLS - 1, env.LED_MATRIX_ROWS - 1)

    # setup font, validating the configured font color exists before the loop starts
    font = graphics.Font()
    font.LoadFont(path.join("fonts", env.FONT))
    getattr(Colors, env.FONT_COLOR)
    # number of display rows that fit on the panel
    max_display_line_count = (env.LED_MATRIX_ROWS - 1) // font.height

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
            # snapshot the dict reference so drawing doesn't block api_loop; safe because api_loop
            # always replaces the dict rather than mutating it in place
            with display_info_lock:
                display_info_snapshot = display_info_dict

            # loop the departure convoy across the display as a loading screen until stop data arrives
            if display_info_snapshot is None or len(display_info_snapshot) == 0:
                apply_sun_based_brightness(canvas)
                canvas = play_loading_animation(matrix, canvas, env.LED_MATRIX_COLS, env.LED_MATRIX_ROWS)
                continue

            now = datetime.now(timezone.utc)
            (
                display_lines,
                display_line_arrival_times,
                display_line_animation_directions,
                display_line_colors,
                display_line_keys,
            ) = build_display_rows(display_info_snapshot, now, max_display_line_count)

            # soonest arrival time shown on the display, used to time the departure animation; when the
            # animation is disabled this stays None so the display never wakes early and never plays it
            next_arrival_time: datetime | None = None
            if env.ENABLE_DEPARTURE_ANIMATION == 1:
                next_arrival_time = min(
                    (arrival_time for row_times in display_line_arrival_times for arrival_time in row_times),
                    default=None,
                )

            graphics_display_line_args = get_display_line_draw_args(
                display_lines, display_line_arrival_times, display_line_colors, font, now
            )

            # LED in bottom right corner of display that acts as a visual indicator for how up-to-date the display
            # info is. Use oldest response timestamp to keep this simple
            oldest_response_timestamp = min(
                [display_info.response_timestamp for display_info in display_info_snapshot.values()]
            )
            logger.debug(f"oldest_response_timestamp: {oldest_response_timestamp}")
            logger.debug(display_info_snapshot)
            status_led_colors = get_status_led_colors(oldest_response_timestamp, env.REFRESH_API_INTERVAL_SECONDS)

            draw_display_frame(canvas, font, graphics_display_line_args, status_led_xy, status_led_colors)
            apply_sun_based_brightness(canvas)

            canvas = matrix.SwapOnVSync(
                canvas
            )  # draw canvas, set returned canvas as new canvas to prevent flickering

            sleep_until_next_frame(next_arrival_time)
            canvas = pulse_imminent_arrivals(
                matrix,
                canvas,
                font,
                next_arrival_time,
                display_line_arrival_times,
                graphics_display_line_args,
                status_led_xy,
                status_led_colors,
            )
            canvas = play_departure_animation_for_due_arrivals(
                matrix,
                canvas,
                font,
                next_arrival_time,
                display_line_arrival_times,
                display_line_keys,
                display_line_animation_directions,
                graphics_display_line_args,
                status_led_xy,
                status_led_colors,
            )
        except Exception:
            logger.error("Unexpected exception while trying to display stop data...terminating program", exc_info=True)
            os._exit(1)


def fetch_stop_display_info(client: OpenData511Client, stopcode: str):
    """Fetches a stop's monitoring data, returning None on request failure so other stops are unaffected"""
    try:
        return client.get_transit_stop_monitoring(env.OPEN_DATA_511_AGENCY_ID, stopcode).convert_to_display_info()
    except HTTPStatusError as err:
        # fail program on 401; an unhandled raise would only kill this thread and leave the display
        # running with stale data forever
        if err.response.status_code == 401:
            logger.error(f"API key rejected for stopcode {stopcode}: 401 {err.response.text}")
            os._exit(1)
        logger.error(f"API Request Failed for stopcode {stopcode}: {err.response.status_code} {err.response.text}")
    except Exception:
        # catch all other errors as the OpenData511 API is fickle and I don't wanna play error whack-a-mole
        logger.error("Unexpected exception while trying to fetch stop data...continuing", exc_info=True)
    return None


def refresh_sunrise_sunset_result(sunrise_sunset_client: SunriseSunsetClient):
    """Fetches sunrise/sunset data for the current date, refreshing the global result once per day"""
    global sunrise_sunset_result

    now = datetime.now(ZoneInfo(env.SUN_BASED_BRIGHTNESS_TZ))
    # if result is not set or the sunrise data is for another date, refresh the data
    # in effect, the sunrise_sunset_result is only refreshed once per day to get data for that day
    if sunrise_sunset_result is not None and sunrise_sunset_result.sunrise.date() == now.date():
        return

    try:
        response = sunrise_sunset_client.get_solar_time_data(
            lat=env.SUN_BASED_BRIGHTNESS_LAT,
            lng=env.SUN_BASED_BRIGHTNESS_LNG,
            tzid=env.SUN_BASED_BRIGHTNESS_TZ,
        )
        with sunrise_sunset_result_lock:
            sunrise_sunset_result = response.results
    except HTTPStatusError as err:
        logger.error(f"API Request Failed for SunriseSunset API: {err.response.status_code} {err.response.text}")
    except Exception:
        logger.error("Unexpected exception while trying to fetch sunrise sunset data...continuing", exc_info=True)


def api_loop():
    global display_info_dict

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
            display_info = fetch_stop_display_info(client_list[client_idx], stopcode)
            if display_info is not None:
                display_info_dict_staged[stopcode] = display_info

        with display_info_lock:
            # NOTE: only want to overwrite stops for data we have fetched in case one of the API requests fails
            # This makes the display fault tolerant to occasional API request failures
            display_info_dict = (display_info_dict or {}) | display_info_dict_staged

        if sunrise_sunset_client is not None:
            refresh_sunrise_sunset_result(sunrise_sunset_client)

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
