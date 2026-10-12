import json
import unittest
from unittest import mock

import modules.animation_registry as animation_registry
from modules.animation_queue import AnimationQueue
from modules.animation_registry import AnimationIntake, RejectedRequest, parse_request


def _payload(animation: str, params: dict | None = None, **envelope):
    body = {"v": 1, "animation": animation, **envelope}
    if params is not None:
        body["params"] = params
    return json.dumps(body).encode()


class _FakeClock:
    def __init__(self):
        self.now = 500.0

    def __call__(self):
        return self.now


class ParseRequestTest(unittest.TestCase):
    def test_accepts_mc_lightings_payloads(self):
        # exactly as mc-lighting's toPayload writes them, every param present
        payloads = {
            b'{"v":1,"animation":"convoy","params":{"sprites":["CHICKEN_JOCKEY","PIG","COW","CREEPER"],"direction":"R"}}': 3.0,
            b'{"v":1,"animation":"flash","params":{"colors":[[255,0,0],[255,90,0],[200,0,0]],"step_ms":600,"repeats":1}}': 1.8,
            b'{"v":1,"animation":"banner","params":{"text":"Steve was blown up by Creeper","color":[255,0,0]}}': (64 + 5 * 29) / 30,
        }
        for payload, duration_seconds in payloads.items():
            with self.subTest(payload):
                self.assertAlmostEqual(parse_request(payload).duration_seconds, duration_seconds)

    def test_fills_defaults_so_equal_requests_share_a_key(self):
        explicit = parse_request(_payload("convoy", {"sprites": ["PIG"], "direction": "R"}))
        defaulted = parse_request(_payload("convoy", {"sprites": ["PIG"]}))
        self.assertEqual(explicit.key, defaulted.key)

    def test_accepts_the_longest_requests_the_contract_allows(self):
        self.assertAlmostEqual(parse_request(_payload("banner", {"text": "x" * 47})).duration_seconds, 299 / 30)
        flash_params = {"colors": [[1, 2, 3]] * 20, "step_ms": 500, "repeats": 1}
        self.assertEqual(parse_request(_payload("flash", flash_params)).duration_seconds, 10.0)

    def test_rejects_requests_that_break_the_contract(self):
        payloads = {
            "garbage bytes": b"\xff\xfe\x00",
            "a JSON array": b"[]",
            "a JSON string": b'"convoy"',
            "missing version": json.dumps({"animation": "convoy", "params": {"sprites": ["PIG"]}}).encode(),
            "version 2": _payload("convoy", {"sprites": ["PIG"]}, v=2),
            "version as a string": _payload("convoy", {"sprites": ["PIG"]}, v="1"),
            "unknown animation": _payload("fireworks", {}),
            "extra envelope field": _payload("convoy", {"sprites": ["PIG"]}, priority=1),
            "params not an object": _payload("convoy", ["PIG"]),  # type: ignore[arg-type]
            "extra param": _payload("convoy", {"sprites": ["PIG"], "speed": 2}),
            "missing required param": _payload("banner", {"color": [255, 0, 0]}),
            "unknown sprite": _payload("convoy", {"sprites": ["ENDER_DRAGON"]}),
            "no sprites": _payload("convoy", {"sprites": []}),
            "seven sprites": _payload("convoy", {"sprites": ["PIG"] * 7}),
            "unknown direction": _payload("convoy", {"sprites": ["PIG"], "direction": "U"}),
            "21 colors": _payload("flash", {"colors": [[1, 2, 3]] * 21}),
            "channel over 255": _payload("flash", {"colors": [[256, 0, 0]]}),
            "two channel color": _payload("flash", {"colors": [[255, 0]]}),
            "float step": _payload("flash", {"colors": [[255, 0, 0]], "step_ms": 700.0}),
            "boolean channel": _payload("flash", {"colors": [[True, 0, 0]]}),
            "step under the floor": _payload("flash", {"colors": [[255, 0, 0]], "step_ms": 499}),
            "flash over 10 s": _payload("flash", {"colors": [[255, 0, 0]] * 20, "step_ms": 2000, "repeats": 4}),
            "48 character banner": _payload("banner", {"text": "x" * 48}),
            "non ASCII banner": _payload("banner", {"text": "café"}),
            "banner with a newline": _payload("banner", {"text": "two\nlines"}),
            "empty banner": _payload("banner", {"text": ""}),
            "over the payload cap": _payload("banner", {"text": "x"}) + b" " * 4096,
        }
        for name, payload in payloads.items():
            with self.subTest(name):
                with self.assertRaises(RejectedRequest):
                    parse_request(payload)

    def test_refuses_flash_while_it_is_disabled(self):
        with mock.patch.object(animation_registry, "FLASH_ENABLED", False):
            with self.assertRaisesRegex(RejectedRequest, "flash is disabled"):
                parse_request(_payload("flash", {"colors": [[255, 255, 255]]}))

    def test_rejection_reasons_never_quote_the_payload(self):
        with self.assertRaises(RejectedRequest) as caught:
            parse_request(_payload("banner", {"text": "evil\ninjected log line"}))
        self.assertNotIn("injected", str(caught.exception))


class AnimationIntakeTest(unittest.TestCase):
    def test_queues_valid_requests(self):
        queue = AnimationQueue()
        AnimationIntake(queue).submit(_payload("convoy", {"sprites": ["PIG"]}))
        self.assertEqual(queue.generation, 1)

    def test_rejections_never_reach_the_queue(self):
        queue = AnimationQueue()
        with self.assertLogs("modules.animation_registry", "WARNING"):
            AnimationIntake(queue).submit(b"not json")
        self.assertEqual(queue.generation, 0)

    def test_logs_rejections_at_most_once_a_minute_with_a_count(self):
        clock = _FakeClock()
        intake = AnimationIntake(AnimationQueue(), clock=clock)
        with self.assertLogs("modules.animation_registry", "WARNING") as logs:
            for _ in range(5):
                intake.submit(b"not json")
            clock.now += 60
            intake.submit(b"not json")
        self.assertEqual(len(logs.output), 2)
        self.assertIn("Rejected 1 animation", logs.output[0])
        self.assertIn("Rejected 5 animation", logs.output[1])

    def test_logged_payloads_are_escaped_and_cut(self):
        with self.assertLogs("modules.animation_registry", "WARNING") as logs:
            AnimationIntake(AnimationQueue()).submit(b"evil\ninjected" + b"x" * 1000)
        self.assertEqual(len(logs.records), 1)
        self.assertNotIn("\n", logs.records[0].getMessage())
        self.assertLess(len(logs.records[0].getMessage()), 500)


if __name__ == "__main__":
    unittest.main()
