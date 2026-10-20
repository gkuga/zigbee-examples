"""The backend side of the Zigbee hello example.

This is the code you would keep when you swap the fake bridge for a real
Zigbee2MQTT: it only talks MQTT to the broker and never touches the coordinator
dongle, the serial link or the radio.

It knows no device in advance. It learns them from bridge/devices, opens the
network for joining, turns on every switch it finds, and makes every button
toggle them.

    uv run app.py
"""

import itertools
import json

import paho.mqtt.client as mqtt

from common import (
    BASE_TOPIC,
    MQTT_HOST,
    MQTT_PORT,
    availability_topic,
    bridge_topic,
    device_topic,
    request_topic,
    response_topic,
    set_topic,
)

PERMIT_JOIN_S = 30


class App:
    def __init__(self, client: mqtt.Client) -> None:
        self.client = client
        self.devices: dict[str, dict] = {}  # friendly_name -> bridge/devices entry
        self.switched_on: set[str] = set()
        self.permit_join: bool | None = None
        self.transactions = itertools.count(1)

    # -- incoming ---------------------------------------------------------

    def on_bridge_state(self, payload: dict) -> None:
        print(f"[app] bridge is {payload['state']}")
        if payload["state"] == "online":
            self.request("permit_join", {"time": PERMIT_JOIN_S})

    def on_bridge_info(self, payload: dict) -> None:
        # bridge/info is republished whenever anything in it changes, so only
        # report what we care about when it changes.
        if self.permit_join is None:
            network = payload["network"]
            print(
                f"[app] network: channel {network['channel']}, "
                f"PAN ID 0x{network['pan_id']:04x}, "
                f"coordinator {payload['coordinator']['type']}"
            )
        if payload["permit_join"] != self.permit_join:
            self.permit_join = payload["permit_join"]
            print(f"[app] permit_join is {'open' if self.permit_join else 'closed'}")

    def on_bridge_devices(self, payload: list) -> None:
        for device in payload:
            name = device["friendly_name"]
            if name not in self.devices:
                definition = device["definition"] or {}
                print(
                    f"[app] device {name}: {device['type']}, "
                    f"{device['ieee_address']} / 0x{device['network_address']:04x}, "
                    f"{definition.get('vendor', '-')} {definition.get('model', '-')}"
                )
            self.devices[name] = device

        for name in self.switches():
            if name not in self.switched_on:
                self.switched_on.add(name)
                self.set(name, {"state": "ON"})

    def on_bridge_event(self, payload: dict) -> None:
        data = payload["data"]
        status = f" ({data['status']})" if "status" in data else ""
        print(f"[app] event {payload['type']}{status}: {data['friendly_name']}")

    def on_bridge_response(self, command: str, payload: dict) -> None:
        result = payload["status"]
        if result != "ok":
            result += f": {payload.get('error')}"
        print(f"[app] {command} #{payload.get('transaction')} -> {result} {payload['data']}")

    def on_availability(self, name: str, payload: dict) -> None:
        print(f"[app] {name} is {payload['state']}")

    def on_device_state(self, name: str, payload: dict) -> None:
        print(f"[app] {name}: {json.dumps(payload, ensure_ascii=False)}")
        if payload.get("action") == "toggle":
            for switch in self.switches():
                self.set(switch, {"state": "TOGGLE"})

    # -- outgoing ---------------------------------------------------------

    def request(self, command: str, payload: dict) -> None:
        """Send a bridge request. The response echoes the transaction."""
        transaction = next(self.transactions)
        self.client.publish(request_topic(command), json.dumps({**payload, "transaction": transaction}))
        print(f"[app] {command} #{transaction} sent: {payload}")

    def set(self, name: str, payload: dict) -> None:
        self.client.publish(set_topic(name), json.dumps(payload))
        print(f"[app] set {name} {payload}")

    def switches(self) -> list[str]:
        """Devices that expose an on/off switch, from their definitions."""
        return [
            name
            for name, device in self.devices.items()
            if any(e["type"] == "switch" for e in (device["definition"] or {}).get("exposes", []))
        ]


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"[app] connection failed: {reason_code}")
        return

    print(f"[app] connected to {MQTT_HOST}:{MQTT_PORT}")
    client.subscribe(
        [
            (bridge_topic("state"), 0),
            (bridge_topic("info"), 0),
            (bridge_topic("devices"), 0),
            (bridge_topic("event"), 0),
            (response_topic(), 0),
            (availability_topic(), 0),
            # Matches exactly one level, so every device but none of the
            # bridge/... or .../set topics.
            (device_topic(), 0),
        ]
    )


def on_message(client, userdata, msg):
    app: App = userdata
    try:
        payload = json.loads(msg.payload)
    except ValueError:
        print(f"[app] not JSON on {msg.topic}: {msg.payload!r}")
        return

    topic = msg.topic.removeprefix(f"{BASE_TOPIC}/")
    handlers = {
        "bridge/state": app.on_bridge_state,
        "bridge/info": app.on_bridge_info,
        "bridge/devices": app.on_bridge_devices,
        "bridge/event": app.on_bridge_event,
    }
    if topic in handlers:
        handlers[topic](payload)
    elif topic.startswith("bridge/response/"):
        app.on_bridge_response(topic.removeprefix("bridge/response/"), payload)
    elif topic.endswith("/availability"):
        app.on_availability(topic.removesuffix("/availability"), payload)
    else:
        app.on_device_state(topic, payload)


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.user_data_set(App(client))
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[app] stopping")
        client.disconnect()


if __name__ == "__main__":
    main()
