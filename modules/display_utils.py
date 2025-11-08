from datetime import datetime, timezone
from enum import StrEnum

from modules.logger import logger


# Common RGB color values as tuples
class Colors:
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)
    YELLOW = (255, 255, 0)
    CYAN = (0, 255, 255)
    MAGENTA = (255, 0, 255)
    GRAY = (128, 128, 128)
    ORANGE = (255, 165, 0)
    PURPLE = (128, 0, 128)
    BROWN = (165, 42, 42)
    PINK = (255, 192, 203)
    LIME = (0, 255, 0)
    NAVY = (0, 0, 128)
    TEAL = (0, 128, 128)
    OLIVE = (128, 128, 0)
    MAROON = (128, 0, 0)
    SILVER = (192, 192, 192)
    GOLD = (255, 215, 0)
    MUNI = (255, 130, 0)
    MUNI_LESS = (150, 30, 0)
    MUNI_ALT = (100, 0, 180)
    MUNI_ALT_LESS = (60, 0, 140)


class FontAlignment(StrEnum):
    CENTER = "CENTER"
    LEFT = "LEFT"


def _calculate_absolute_time_difference_from_now(datetime_obj: datetime, tz_aware_now: datetime):
    """Calculates difference in time between now and a provided datetime. Handles both naive and aware datetime objects.
    Assumes UTC for naive datetime objects

    Args:
        datetime_obj (datetime): datetime object to calculate time difference from now for
        tz_aware_now (datetime) (optional): datetime object representing now to compare against, must be tz-aware with tzinfo of timezone.utc

    Returns:
        datetime.timedelta: difference between now and datetime_obj
    """
    if tz_aware_now.tzinfo is None or tz_aware_now.tzinfo != timezone.utc:
        raise ValueError("tz_aware_now must be an aware datetime with utc timestamp")

    datetime_obj_utc = datetime_obj.astimezone(timezone.utc)
    difference = abs(datetime_obj_utc - tz_aware_now)
    logger.debug(f"difference: {difference}")
    return difference


def get_status_led_colors(update_datetime: datetime, refresh_interval_seconds: int):
    """Status LED that transitions from green to yellow to red as update_datetime becomes more stale
    Green -> update_datetime is < (refresh_interval_seconds * 2) seconds in the past
    Yellow -> update_datetime is < (refresh_interval_seconds * 4) seconds in the past
    RED -> update_datetime is >= (refresh_interval_seconds * 4) seconds in the past

    Args:
        update_datetime (datetime): time when update was performed
        refresh_interval_seconds (int): refresh interval in seconds

    Returns:
        (int, int, int): tuple representing led color in RGB
    """
    difference = _calculate_absolute_time_difference_from_now(update_datetime, datetime.now(timezone.utc))

    if difference.seconds < refresh_interval_seconds * 2:
        return Colors.GREEN
    if difference.seconds < refresh_interval_seconds * 4:
        return Colors.YELLOW

    return Colors.RED  # information is very out of date


def get_text_center_x_pos(text: str, character_width: int, display_width: int):
    """Calculates the x position for centering text on a display

    Args:
        text (str): text to center
        character_width (int): width of a character in the used font
        display_width (int): width of the display to center text on

    Returns:
        int: x position which will center the text on the display
    """
    text_length = len(text)
    text_width = text_length * character_width
    center_display_pixel = (display_width - 1) / 2
    text_offset = text_width / 2
    character_offset = character_width / 4
    return int(center_display_pixel - text_offset + character_offset)  # bias left through truncation


def get_text_center_y_pos(character_height: int, display_height: int):
    """Calculates the y position for centering text on a display

    Args:
        character_height (int): height of a character in the used font
        display_height (int): height of the display to center text on

    Returns:
        int: y position which will center the text on the display
    """
    center_display_pixel = (display_height - 1) // 2  # bias up
    text_offset = character_height // 2  # bias up
    return center_display_pixel + text_offset


def get_text_x_pos(text: str, character_width: int, display_width: int, text_alignment: FontAlignment):
    return (
        get_text_center_x_pos(text, character_width, display_width) if text_alignment == FontAlignment.CENTER else 2
    )  # offset a couple pixels when left aligned so text isn't right at display edge


def generate_display_line_row(
    line_reference: str,
    line_disambiguation_symbol: str,
    line_arrival_times: list[datetime],
    now=datetime.now(timezone.utc),
):
    """Formats a line reference, disambiguation symbol, and line arrival times into an inline string

    Args:
        line_reference (str): Line reference value
        line_disambiguation_symbol (str): Symbol used for disambiguating lines with the same reference
        line_arrival_times (list[datetime]): Arrival times for the given line
        now (datetime) (optional): Datetime object from which to compare times to, must be tz-aware and in UTC

    Returns:
        str: Inline string representing a line and its arrival times
    """
    logger.debug(f"line_reference: {line_reference}")
    logger.debug(f"line_disambiguation_symbol: {line_disambiguation_symbol}")
    logger.debug(f"line_arrival_times: {line_arrival_times}")
    time_until_arrival_minutes_list: list[str] = []

    for arrival_time in line_arrival_times:
        difference = _calculate_absolute_time_difference_from_now(arrival_time, now)
        # round down to nearest minute
        difference_str = str(difference.seconds // 60)
        # prepend single digit arrival times with 0 for alignment consistency
        difference_str_padded = difference_str if len(difference_str) > 1 else "0" + difference_str
        time_until_arrival_minutes_list.append(difference_str_padded)

    display_line = (
        f"{line_reference}{line_disambiguation_symbol} " + " ".join(time_until_arrival_minutes_list)
    ).replace("0", "O")  # in the provided fonts the 0 is skinny and looks awful so use O instead
    logger.debug(f"display_line: {display_line}")
    return display_line
