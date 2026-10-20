"""Shared settings and topic helpers for the Zigbee hello example.

Topic names follow the Zigbee2MQTT MQTT API (v2), which is what a real
Zigbee2MQTT instance publishes. Every payload is JSON:

    zigbee2mqtt/bridge/state                   {"state": "online"}, retained
    zigbee2mqtt/bridge/info                    network, coordinator, permit_join, retained
    zigbee2mqtt/bridge/devices                 every device and what it can do, retained
    zigbee2mqtt/bridge/event                   device_joined, device_interview, ...
    zigbee2mqtt/bridge/request/<command>       backend -> bridge
    zigbee2mqtt/bridge/response/<command>      bridge -> backend
    zigbee2mqtt/<friendly_name>                device state
    zigbee2mqtt/<friendly_name>/set            backend -> device
    zigbee2mqtt/<friendly_name>/availability   {"state": "online"}, retained

Unlike the Wirepas example, nothing about the devices lives here: the backend
learns them from bridge/devices at runtime.
"""

import os

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# `mqtt.base_topic` in the Zigbee2MQTT configuration.
BASE_TOPIC = os.environ.get("Z2M_BASE_TOPIC", "zigbee2mqtt")


def bridge_topic(name: str) -> str:
    return f"{BASE_TOPIC}/bridge/{name}"


def request_topic(command: str = "+") -> str:
    return bridge_topic(f"request/{command}")


def response_topic(command: str = "+") -> str:
    # No transaction id in the topic: a response is matched to its request by
    # the "transaction" field echoed back in the JSON payload.
    return bridge_topic(f"response/{command}")


def device_topic(friendly_name: str = "+") -> str:
    return f"{BASE_TOPIC}/{friendly_name}"


def set_topic(friendly_name: str = "+") -> str:
    return f"{BASE_TOPIC}/{friendly_name}/set"


def availability_topic(friendly_name: str = "+") -> str:
    return f"{BASE_TOPIC}/{friendly_name}/availability"
