import unittest
from unittest import mock

from paho.mqtt.subscribeoptions import SubscribeOptions

import modules.animation_mqtt as animation_mqtt
from modules.animation_mqtt import ANIMATION_TOPIC, DEPARTURE_CONVOY_TOPIC, STATUS_TOPIC, AnimationListener
from modules.departure_convoy import DepartureConvoy

_ROCKY = b'{"v": 1, "sprites": ["ROCKY_ANGRY"]}'


class _ReasonCode:
    def __init__(self, is_failure: bool):
        self.is_failure = is_failure

    def __str__(self):
        return "Not authorized" if self.is_failure else "Success"


class _Message:
    def __init__(self, payload: bytes, topic: str = ANIMATION_TOPIC):
        self.payload = payload
        self.topic = topic


def _listener(submit=lambda payload: None, submit_departure_convoy=None):
    with mock.patch.object(animation_mqtt.mqtt, "Client") as client_class:
        listener = AnimationListener(
            "broker.local", 1883, "user", "password", submit, submit_departure_convoy=submit_departure_convoy
        )
    return listener, client_class.return_value


def _subscriptions(client):
    (subscriptions,) = client.subscribe.call_args.args
    return {topic: options for topic, options in subscriptions}


def _client_kwargs():
    with mock.patch.object(animation_mqtt.mqtt, "Client") as client_class:
        AnimationListener("broker.local", 1883, "user", "password", lambda payload: None)
    return client_class.call_args.kwargs


class ClientTest(unittest.TestCase):
    def test_uses_a_stable_client_id_per_host(self):
        with mock.patch.object(animation_mqtt.socket, "gethostname", return_value="muni-display"):
            self.assertEqual(_client_kwargs()["client_id"], "transit-display-muni-display")


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
        self.assertEqual(client.subscribe.call_count, 2)
        self.assertEqual(list(_subscriptions(client)), [ANIMATION_TOPIC])
        self.assertEqual(client.publish.call_args_list, [mock.call(STATUS_TOPIC, "online", qos=1, retain=True)] * 2)

    def test_never_asks_for_retained_messages(self):
        listener, _ = _listener()
        client = mock.Mock()
        listener._on_connect(client, None, None, _ReasonCode(False), None)
        options = _subscriptions(client)[ANIMATION_TOPIC]
        self.assertEqual(options.QoS, 0)
        self.assertEqual(options.retainHandling, SubscribeOptions.RETAIN_DO_NOT_SEND)

    def test_asks_for_the_retained_departure_convoy_when_it_has_a_callback(self):
        listener, _ = _listener(submit_departure_convoy=lambda payload: None)
        client = mock.Mock()
        listener._on_connect(client, None, None, _ReasonCode(False), None)
        subscriptions = _subscriptions(client)
        self.assertEqual(list(subscriptions), [ANIMATION_TOPIC, DEPARTURE_CONVOY_TOPIC])
        # the last swap is resent on every connect, so a reboot keeps it
        self.assertEqual(
            subscriptions[DEPARTURE_CONVOY_TOPIC].retainHandling, SubscribeOptions.RETAIN_SEND_ON_SUBSCRIBE
        )
        self.assertEqual(subscriptions[DEPARTURE_CONVOY_TOPIC].QoS, 1)
        self.assertEqual(subscriptions[ANIMATION_TOPIC].retainHandling, SubscribeOptions.RETAIN_DO_NOT_SEND)

    def test_resets_the_departure_convoy_before_subscribing(self):
        calls = mock.Mock()
        listener, _ = _listener(submit_departure_convoy=calls.submit_departure_convoy)
        listener._on_connect(calls.client, None, None, _ReasonCode(False), None)
        # cleared first, so the retained message the subscription brings is what decides the convoy
        self.assertEqual(calls.mock_calls[0], mock.call.submit_departure_convoy(b""))
        self.assertEqual(calls.mock_calls[1][0], "client.subscribe")

    def test_a_refill_missed_while_offline_ends_the_swap_on_reconnect(self):
        convoy = DepartureConvoy()
        listener, _ = _listener(submit_departure_convoy=convoy.submit)
        listener._on_connect(mock.Mock(), None, None, _ReasonCode(False), None)
        listener._on_message(None, None, _Message(_ROCKY, DEPARTURE_CONVOY_TOPIC))
        # the clear was published while the display was offline, deleting the retained swap, so the reconnect
        # brings no message at all
        listener._on_connect(mock.Mock(), None, None, _ReasonCode(False), None)
        self.assertEqual(convoy.swapped_sprite_names(), None)

    def test_a_swap_still_retained_is_restored_on_reconnect(self):
        convoy = DepartureConvoy()
        listener, _ = _listener(submit_departure_convoy=convoy.submit)
        listener._on_connect(mock.Mock(), None, None, _ReasonCode(False), None)
        listener._on_message(None, None, _Message(_ROCKY, DEPARTURE_CONVOY_TOPIC))
        listener._on_connect(mock.Mock(), None, None, _ReasonCode(False), None)
        listener._on_message(None, None, _Message(_ROCKY, DEPARTURE_CONVOY_TOPIC))
        self.assertEqual(convoy.swapped_sprite_names(), ("ROCKY_ANGRY",))

    def test_a_refused_connect_keeps_the_departure_convoy(self):
        convoy = DepartureConvoy()
        convoy.submit(_ROCKY)
        listener, _ = _listener(submit_departure_convoy=convoy.submit)
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_connect(mock.Mock(), None, None, _ReasonCode(True), None)
        self.assertEqual(convoy.swapped_sprite_names(), ("ROCKY_ANGRY",))

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

    def test_routes_each_topic_to_its_own_callback(self):
        animations, convoys = [], []
        listener, _ = _listener(animations.append, convoys.append)
        listener._on_message(None, None, _Message(b"play", ANIMATION_TOPIC))
        listener._on_message(None, None, _Message(b"swap", DEPARTURE_CONVOY_TOPIC))
        listener._on_message(None, None, _Message(b"stray", "transit-display/other"))
        self.assertEqual((animations, convoys), ([b"play"], [b"swap"]))

    def test_a_departure_convoy_message_is_ignored_without_its_callback(self):
        received = []
        listener, _ = _listener(received.append)
        listener._on_message(None, None, _Message(b"swap", DEPARTURE_CONVOY_TOPIC))
        self.assertEqual(received, [])

    def test_a_missing_payload_is_logged_not_raised(self):
        listener, _ = _listener()
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_message(None, None, object())


class OnSubscribeTest(unittest.TestCase):
    def test_logs_a_refused_subscription(self):
        listener, _ = _listener()
        with self.assertLogs("modules.animation_mqtt", "ERROR"):
            listener._on_subscribe(None, None, 1, [_ReasonCode(True)], None)

    def test_names_the_topic_whose_subscription_was_refused(self):
        listener, _ = _listener(submit_departure_convoy=lambda payload: None)
        with self.assertLogs("modules.animation_mqtt", "ERROR") as logs:
            listener._on_subscribe(None, None, 1, [_ReasonCode(False), _ReasonCode(True)], None)
        self.assertEqual(len(logs.output), 1)
        self.assertIn(DEPARTURE_CONVOY_TOPIC, logs.output[0])

    def test_a_granted_subscription_logs_nothing(self):
        listener, _ = _listener()
        with self.assertNoLogs("modules.animation_mqtt", "ERROR"):
            listener._on_subscribe(None, None, 1, [_ReasonCode(False)], None)


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
