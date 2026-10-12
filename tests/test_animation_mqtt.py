import unittest
from unittest import mock

import modules.animation_mqtt as animation_mqtt
from modules.animation_mqtt import ANIMATION_TOPIC, STATUS_TOPIC, AnimationListener


class _ReasonCode:
    def __init__(self, is_failure: bool):
        self.is_failure = is_failure

    def __str__(self):
        return "Not authorized" if self.is_failure else "Success"


class _Message:
    def __init__(self, payload: bytes):
        self.payload = payload


def _listener(submit=lambda payload: None):
    with mock.patch.object(animation_mqtt.mqtt, "Client") as client_class:
        listener = AnimationListener("broker.local", 1883, "user", "password", submit)
    return listener, client_class.return_value


class StartTest(unittest.TestCase):
    def test_sets_the_offline_will_before_connecting(self):
        _, client = _listener()
        client.will_set.assert_called_once_with(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.username_pw_set.assert_called_once_with("user", "password")

    def test_connects_in_the_background_asking_for_small_packets_only(self):
        listener, client = _listener()
        listener.start()
        client.connect_async.assert_called_once()
        self.assertEqual(client.connect_async.call_args.args[:2], ("broker.local", 1883))
        self.assertEqual(client.connect_async.call_args.kwargs["properties"].MaximumPacketSize, 8192)
        client.loop_start.assert_called_once()
        client.connect.assert_not_called()
        client.disconnect.assert_not_called()

    def test_suppresses_callback_exceptions_as_a_second_line(self):
        _, client = _listener()
        self.assertIs(client.suppress_exceptions, True)


class OnConnectTest(unittest.TestCase):
    def test_subscribes_and_announces_online_on_every_connect(self):
        listener, _ = _listener()
        client = mock.Mock()
        listener._on_connect(client, None, None, _ReasonCode(False), None)
        listener._on_connect(client, None, None, _ReasonCode(False), None)
        self.assertEqual(client.subscribe.call_args_list, [mock.call(ANIMATION_TOPIC, qos=0)] * 2)
        self.assertEqual(client.publish.call_args_list, [mock.call(STATUS_TOPIC, "online", qos=1, retain=True)] * 2)

    def test_a_refused_connect_is_logged_without_subscribing(self):
        listener, _ = _listener()
        client = mock.Mock()
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_connect(client, None, None, _ReasonCode(True), None)
        client.subscribe.assert_not_called()

    def test_errors_never_escape(self):
        listener, _ = _listener()
        client = mock.Mock()
        client.subscribe.side_effect = OSError("socket closed")
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_connect(client, None, None, _ReasonCode(False), None)


class OnMessageTest(unittest.TestCase):
    def test_hands_the_payload_to_submit(self):
        received = []
        listener, _ = _listener(received.append)
        listener._on_message(None, None, _Message(b'{"v":1}'))
        self.assertEqual(received, [b'{"v":1}'])

    def test_errors_never_escape_the_network_thread(self):
        def submit(payload):
            raise RuntimeError("intake bug")

        listener, _ = _listener(submit)
        for payload in (b"", b"\xff\xfe", b"[]", b"x" * 10000):
            with self.subTest(payload[:10]):
                with self.assertLogs("modules.animation_mqtt", "ERROR"):
                    listener._on_message(None, None, _Message(payload))

    def test_a_missing_payload_is_logged_not_raised(self):
        listener, _ = _listener()
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_message(None, None, object())


class OnConnectFailTest(unittest.TestCase):
    def test_logs_which_broker_could_not_be_reached(self):
        listener, _ = _listener()
        with self.assertLogs("modules.animation_mqtt", "WARNING") as logs:
            listener._on_connect_fail(None, None)
        self.assertIn("broker.local:1883", logs.output[0])


class OnDisconnectTest(unittest.TestCase):
    def test_logs_and_returns(self):
        listener, _ = _listener()
        with self.assertLogs("modules.animation_mqtt", "WARNING"):
            listener._on_disconnect(None, None, None, _ReasonCode(True), None)


if __name__ == "__main__":
    unittest.main()
