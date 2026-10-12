"""The bounded queue between the MQTT thread that submits animation requests and the display thread that plays them

Kept free of modules.environment so it can be tested with any configuration.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from modules.animation_player import AnimationRequest

logger = logging.getLogger(__name__)

# contract constants, publishers rely on these so they are not configuration
QUEUE_MAX_REQUESTS = 3
# covers a short animation waiting out a departure's pulse and animation. A long one blocked early can wait
# about 18.5 s and expire instead, since a late animation is worse than none
REQUEST_TTL_SECONDS = 15.0


@dataclass(frozen=True)
class _WaitingRequest:
    request: AnimationRequest
    received_at: float


class AnimationQueue:
    """Holds at most QUEUE_MAX_REQUESTS requests in arrival order, dropping the oldest when full

    A generation counter moves only when a request is enqueued. The display thread is the only one that waits and
    pops, so the queue keeps the last generation that thread saw itself: a request submitted mid-pass makes the
    next wait return at once, while requests that are only waiting never wake it, so one that can't start yet
    never makes the display loop spin
    """

    def __init__(self, max_requests: int = QUEUE_MAX_REQUESTS, ttl_seconds: float = REQUEST_TTL_SECONDS, clock: Callable[[], float] = monotonic):
        self._max_requests = max_requests
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._waiting: deque[_WaitingRequest] = deque()
        self._condition = threading.Condition()
        self._generation = 0
        self._seen_generation = 0

    @property
    def generation(self):
        with self._condition:
            return self._generation

    def put(self, request: AnimationRequest):
        """Enqueues a request, returning False when an equal one is already waiting and it was coalesced into it"""
        with self._condition:
            if any(waiting.request.key == request.key for waiting in self._waiting):
                return False
            if len(self._waiting) >= self._max_requests:
                dropped = self._waiting.popleft()
                logger.info(f"Animation queue full, dropped the oldest request: {dropped.request.animation.name}")
            self._waiting.append(_WaitingRequest(request, self._clock()))
            self._generation += 1
            self._condition.notify_all()
            return True

    def has_waiting(self):
        with self._condition:
            return len(self._waiting) > 0

    def wait_for_new(self, timeout_seconds: float):
        """Blocks until a request the display thread hasn't seen arrives, or the timeout passes"""
        with self._condition:
            self._condition.wait_for(lambda: self._generation != self._seen_generation, max(timeout_seconds, 0))
            self._seen_generation = self._generation

    def pop_if_startable(self, can_start: Callable[[float], bool]):
        """Drops expired requests at the head, then pops the head if can_start(its duration) allows it

        Only the head is ever considered, so requests play in the order they arrived

        Returns:
            AnimationRequest | None: the request to play now, if any
        """
        with self._condition:
            self._seen_generation = self._generation
            now = self._clock()
            while self._waiting and now - self._waiting[0].received_at > self._ttl_seconds:
                expired = self._waiting.popleft()
                logger.info(f"Animation request expired before it could play: {expired.request.animation.name}")
            if self._waiting and can_start(self._waiting[0].request.duration_seconds):
                return self._waiting.popleft().request
            return None
