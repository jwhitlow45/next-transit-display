"""The MQTT adapter in front of the animation intake: one outbound connection to the broker, no listening port

The display runs as root for its whole life on a host with no firewall, so it never opens a port of its own.
Kept free of modules.environment, so the broker settings are passed in.
"""

import logging
import socket
from typing import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

logger = logging.getLogger(__name__)

# contract version 1 constants, fixed on both sides rather than configured
ANIMATION_TOPIC = "transit-display/animations/play"
STATUS_TOPIC = "transit-display/status"
# sent as the MQTT v5 Maximum Packet Size, so the broker never forwards a larger packet to the display and an
# oversized publish can't exhaust the Pi's memory before the intake's 4 KiB payload check
_MAX_PACKET_BYTES = 8192
_KEEPALIVE_SECONDS = 60


class AnimationListener:
    """Subscribes to the animation topic and hands every payload to submit, on paho's network thread"""

    def __init__(self, host: str, port: int, username: str, password: str, submit: Callable[[bytes], None]):
        self._host = host
        self._port = port
        self._submit = submit
        # a stable id lets the broker take over the old session when the display reconnects after a hard reset,
        # publishing the dead connection's offline will before the new online rather than 90 s after it. The
        # hostname keeps a test run on another machine from taking over the Pi's session
        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"transit-display-{socket.gethostname()}",
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(username, password)
        # the broker publishes the will when the connection drops without an MQTT DISCONNECT, which is how the
        # process ends when systemd stops it. Calling disconnect() on shutdown would suppress it, so nothing does
        self._client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        # the callbacks catch everything themselves. This is a second line, since an exception escaping a
        # callback would end paho's network thread for good with no reconnect
        self._client.suppress_exceptions = True

    def start(self):
        """Connects in the background and keeps reconnecting, so a broker that is down never blocks the display"""
        properties = Properties(PacketTypes.CONNECT)
        properties.MaximumPacketSize = _MAX_PACKET_BYTES
        self._client.connect_async(self._host, self._port, keepalive=_KEEPALIVE_SECONDS, properties=properties)
        self._client.loop_start()

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        try:
            if reason_code.is_failure:
                logger.error(f"Animation listener could not connect to the MQTT broker: {reason_code}")
                return
            # on every connect rather than once, so the subscription and status survive reconnects
            client.subscribe(ANIMATION_TOPIC, qos=0)
            client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
            logger.info(f"Animation listener connected to the MQTT broker, listening on {ANIMATION_TOPIC}")
        except Exception:
            logger.error("Animation listener failed handling a connect", exc_info=True)

    def _on_connect_fail(self, client, userdata):
        try:
            # paho backs off up to two minutes between attempts, so this can't flood the log
            logger.warning(f"Animation listener could not reach the MQTT broker at {self._host}:{self._port}, retrying")
        except Exception:
            logger.error("Animation listener failed handling a connect failure", exc_info=True)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        try:
            logger.warning(f"Animation listener lost the MQTT broker, reconnecting: {reason_code}")
        except Exception:
            logger.error("Animation listener failed handling a disconnect", exc_info=True)

    def _on_message(self, client, userdata, message):
        try:
            self._submit(message.payload)
        except Exception:
            logger.error("Animation listener failed handling a message", exc_info=True)
