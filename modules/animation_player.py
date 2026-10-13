"""Plays event animations requested over MQTT, and decides when one may start around transit departures

Kept free of modules.environment so the start rule and frame loop can be tested with any configuration. Logs go
through the standard logging tree, which modules/logger.py configures when the display runs.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic, sleep
from typing import Annotated, Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_FRAMES_PER_SECOND = 30
# transit view kept between two event animations, so back-to-back flashes never change colour faster than
# the flash animation's own 500 ms floor
MIN_GAP_SECONDS = 0.5
# full-panel fills light all 2048 pixels on a supply shared with the Pi, which already reports under-voltage.
# LED drivers draw current by each channel's drive, not by how bright a color looks, so this caps the
# brightest channel rather than perceived luminance, which would let full blue through
FILL_CHANNEL_CAP = 60

# every color in an animation request is an RGB triple of integers 0 to 255
RGBColor = tuple[Annotated[int, Field(ge=0, le=255)], Annotated[int, Field(ge=0, le=255)], Annotated[int, Field(ge=0, le=255)]]


@dataclass(frozen=True)
class AnimationContext:
    """What an animation may draw with besides its params: the 5x7 font and the panel's size"""

    font_5x7: Any
    width: int
    height: int


@dataclass(frozen=True)
class Animation:
    """One playable animation, see the modules in animations/

    duration_seconds(params) is the contract's duration formula. draw_frame(canvas, elapsed_seconds, params,
    context) draws one frame onto an already cleared canvas.
    """

    name: str
    params_model: type[BaseModel]
    duration_seconds: Callable[[Any], float]
    draw_frame: Callable[[Any, float, Any, AnimationContext], None]


@dataclass(frozen=True)
class AnimationRequest:
    """A validated request to play an animation

    key identifies requests for the same animation with the same params, so duplicates waiting together play once
    """

    animation: Animation
    params: BaseModel
    duration_seconds: float
    key: str


def can_start(
    now: datetime,
    next_arrival_time: datetime | None,
    duration_seconds: float,
    pulse_window_seconds: float,
    seconds_since_last_end: float | None,
):
    """Whether an event animation of the given duration may start now

    It must leave MIN_GAP_SECONDS of transit view after the last one, and must finish before the pulse ahead of
    the next displayed departure. Running across a departure would skip its departure animation, since the next
    pass drops arrivals already in the past. With no displayed arrival, or departures disabled, nothing is due.
    The gap is measured on the monotonic clock, since the Pi has no real time clock and its wall clock can step
    back after boot. Arrivals are wall clock times, so the departure check has to stay on the wall clock.
    """
    if seconds_since_last_end is not None and seconds_since_last_end < MIN_GAP_SECONDS:
        return False
    if next_arrival_time is None:
        return True
    return now + timedelta(seconds=duration_seconds) < next_arrival_time - timedelta(seconds=pulse_window_seconds)


def cap_fill_channels(color: tuple[int, int, int]):
    """Scales a fill color uniformly, keeping its hue, so its brightest channel is at most FILL_CHANNEL_CAP"""
    brightest_channel = max(color)
    if brightest_channel <= FILL_CHANNEL_CAP:
        return color
    scale = FILL_CHANNEL_CAP / brightest_channel
    return (round(color[0] * scale), round(color[1] * scale), round(color[2] * scale))


def fill_panel(canvas, color: tuple[int, int, int]):
    """Fills the whole panel through the power guard, which is how every animation must fill it

    The player can't intercept Fill itself by wrapping the canvas: rgbmatrix's graphics functions such as
    DrawText only accept its own canvas type, so animations are handed the real canvas
    """
    canvas.Fill(*cap_fill_channels(color))


def play_animation(matrix, canvas, request: AnimationRequest, context: AnimationContext, clock=monotonic, wait=sleep):
    """Plays one event animation over the whole panel, returning the canvas to keep drawing on

    An exception from the animation is logged and ends it early rather than reaching display_loop, which would
    take the transit view down with an optional animation

    Args:
        matrix: RGBMatrix object to swap animation frames onto
        canvas: back buffer canvas to draw the next frame on
        request (AnimationRequest): the animation and its validated params
        context (AnimationContext): the font and panel size the animation draws with
        clock: monotonic clock, replaceable in tests
        wait: sleep between frames, replaceable in tests

    Returns:
        canvas: back buffer canvas returned by the final frame swap, use this in place of the canvas passed in
    """
    start_time = clock()
    try:
        while (elapsed_seconds := clock() - start_time) < request.duration_seconds:
            canvas.Clear()
            request.animation.draw_frame(canvas, elapsed_seconds, request.params, context)
            canvas = matrix.SwapOnVSync(canvas)
            wait(1 / _FRAMES_PER_SECOND)
    except Exception:
        logger.error(f"Animation {request.animation.name} failed, back to the transit view", exc_info=True)
    return canvas
