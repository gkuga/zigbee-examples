"""A fake Zigbee2MQTT.

It stands in for the whole hardware side of the stack -- the Zigbee devices,
the coordinator dongle and Zigbee2MQTT itself -- and speaks the same MQTT API a
real Zigbee2MQTT does. That is enough to develop and test a backend
application without any hardware.

Underneath, it keeps a small model of what Zigbee2MQTT hides: devices with a
64-bit IEEE address and a 16-bit network address, endpoints, ZCL clusters and
raw attribute values. The log shows each one being converted to the JSON the
backend sees, and back.

    uv run zigbee2mqtt_mock.py
"""

import json
import random
import threading
import time

import paho.mqtt.client as mqtt

from common import (
    MQTT_HOST,
    MQTT_PORT,
    availability_topic,
    bridge_topic,
    device_topic,
    request_topic,
    response_topic,
    set_topic,
)

REPORT_INTERVAL_S = 5
JOIN_DELAY_S = 3  # how long the new device takes to show up once joining is allowed
PRESS_DELAY_S = 2  # and how long until someone presses it

# The network the fake coordinator formed. Channel 11 and PAN ID 0x1a62 were
# Zigbee2MQTT's defaults before it started generating them.
CHANNEL = 11
PAN_ID = 0x1A62
EXTENDED_PAN_ID = "0xdddddddddddddddd"
COORDINATOR_IEEE = "0x00124b0018e2a0f1"

# ZCL access bits used in "exposes": 1 = published, 2 = settable, 4 = readable.
ACCESS_STATE = 1
ACCESS_ALL = 7


def numeric(name: str, unit: str, description: str) -> dict:
    return {
        "type": "numeric",
        "name": name,
        "property": name,
        "access": ACCESS_STATE,
        "unit": unit,
        "description": description,
    }


LINKQUALITY = numeric("linkquality", "lqi", "Link quality (signal strength)")
BATTERY = numeric("battery", "%", "Remaining battery in %")
SWITCH = {
    "type": "switch",
    "features": [
        {
            "type": "binary",
            "name": "state",
            "property": "state",
            "access": ACCESS_ALL,
            "value_on": "ON",
            "value_off": "OFF",
            "value_toggle": "TOGGLE",
        }
    ],
}


class Device:
    """One Zigbee node as the coordinator sees it.

    The models and vendor are made up; everything else has the shape a real
    Zigbee2MQTT reports.
    """

    def __init__(
        self,
        ieee_address: str,
        network_address: int,
        friendly_name: str,
        device_type: str,
        power_source: str,
        model: str,
        description: str,
        input_clusters: list[str],
        output_clusters: list[str],
        exposes: list[dict],
        lqi: int,
    ) -> None:
        self.ieee_address = ieee_address
        self.network_address = network_address
        self.friendly_name = friendly_name
        self.type = device_type
        self.power_source = power_source
        self.model = model
        self.description = description
        # Input clusters are the ones the device serves (it holds the
        # attributes); output clusters are the ones it uses as a client, i.e.
        # sends commands to someone else.
        self.input_clusters = input_clusters
        self.output_clusters = output_clusters
        self.exposes = exposes
        self.lqi = lqi
        self.state: dict = {}
        self.lock = threading.Lock()

    @property
    def nwk(self) -> str:
        return f"0x{self.network_address:04x}"

    def definition(self) -> dict:
        return {
            "source": "native",
            "model": self.model,
            "vendor": "Example",
            "description": self.description,
            "options": [],
            "exposes": self.exposes,
        }

    def to_json(self) -> dict:
        """One entry of bridge/devices."""
        return {
            "ieee_address": self.ieee_address,
            "type": self.type,
            "network_address": self.network_address,
            "supported": True,
            "disabled": False,
            "friendly_name": self.friendly_name,
            "endpoints": {
                "1": {
                    "bindings": [],
                    "configured_reportings": [],
                    "clusters": {
                        "input": self.input_clusters,
                        "output": self.output_clusters,
                    },
                    "scenes": [],
                }
            },
            "definition": self.definition(),
            "power_source": self.power_source,
            "model_id": self.model,
            "interview_state": "SUCCESSFUL",
            "interview_completed": True,
            "interviewing": False,
        }

    def update_state(self, values: dict) -> dict:
        """Merge new values into the cached state and return the whole of it.

        Zigbee2MQTT caches device state (`cache_state`, on by default) and
        publishes all of it on every change, so a humidity report still
        carries the last temperature.
        """
        with self.lock:
            self.state.update(values)
            self.state["linkquality"] = self.lqi
            return dict(self.state)


COORDINATOR = {
    "ieee_address": COORDINATOR_IEEE,
    "type": "Coordinator",
    "network_address": 0,  # the coordinator is always 0x0000
    "supported": True,
    "disabled": False,
    "friendly_name": "Coordinator",
    "definition": None,
    "interview_state": "SUCCESSFUL",
    "interview_completed": True,
    "interviewing": False,
}

SENSOR = Device(
    ieee_address="0x00158d0001a2b3c4",
    network_address=0x6F3C,
    friendly_name="hello_sensor",
    device_type="EndDevice",  # sleeps most of the time, never routes
    power_source="Battery",
    model="HELLO-TH",
    description="Temperature and humidity sensor",
    input_clusters=["genBasic", "genPowerCfg", "msTemperatureMeasurement", "msRelativeHumidity"],
    output_clusters=[],
    exposes=[
        numeric("temperature", "°C", "Measured temperature value"),
        numeric("humidity", "%", "Measured relative humidity"),
        BATTERY,
        LINKQUALITY,
    ],
    lqi=120,
)

PLUG = Device(
    ieee_address="0x0017880100aabbcc",
    network_address=0x4C21,
    friendly_name="hello_plug",
    device_type="Router",  # mains powered, so it also relays for others
    power_source="Mains (single phase)",
    model="HELLO-PLUG",
    description="Smart plug",
    input_clusters=["genBasic", "genOnOff"],
    output_clusters=[],
    exposes=[SWITCH, LINKQUALITY],
    lqi=220,
)

# Not on the network yet: it joins once the backend permits joining. Without a
# friendly name configured, Zigbee2MQTT names a device after its IEEE address.
BUTTON = Device(
    ieee_address="0x00124b0001ddeeff",
    network_address=0x9A07,
    friendly_name="0x00124b0001ddeeff",
    device_type="EndDevice",
    power_source="Battery",
    model="HELLO-BTN",
    description="Wireless button",
    input_clusters=["genBasic", "genPowerCfg"],
    output_clusters=["genOnOff"],  # a client: it sends On/Off commands
    exposes=[
        {
            "type": "enum",
            "name": "action",
            "property": "action",
            "access": ACCESS_STATE,
            "values": ["on", "off", "toggle"],
        },
        BATTERY,
        LINKQUALITY,
    ],
    lqi=95,
)


class Bridge:
    """What Zigbee2MQTT knows: the devices on the network and permit_join."""

    def __init__(self, client: mqtt.Client) -> None:
        self.client = client
        self.lock = threading.Lock()
        self.devices = {d.friendly_name: d for d in (SENSOR, PLUG)}
        self.permit_join_end: int | None = None  # ms since epoch
        self.close_timer: threading.Timer | None = None

    # -- bridge topics ----------------------------------------------------

    def publish(self, topic: str, payload: dict | list, retain: bool = False) -> None:
        self.client.publish(topic, json.dumps(payload), retain=retain)

    def publish_state(self, state: str) -> None:
        self.publish(bridge_topic("state"), {"state": state}, retain=True)
        print(f"[z2m] bridge/state -> {state}")

    def publish_info(self) -> None:
        # A real bridge also sends its whole config, the config schema, OS and
        # library versions.
        self.publish(
            bridge_topic("info"),
            {
                "version": "mock",
                "coordinator": {"ieee_address": COORDINATOR_IEEE, "type": "zStack3x0", "meta": {}},
                "network": {
                    "channel": CHANNEL,
                    "pan_id": PAN_ID,
                    "extended_pan_id": EXTENDED_PAN_ID,
                },
                "log_level": "info",
                "permit_join": self.permit_join_end is not None,
                "permit_join_end": self.permit_join_end,
            },
            retain=True,
        )

    def publish_devices(self) -> None:
        with self.lock:
            devices = [COORDINATOR] + [d.to_json() for d in self.devices.values()]
        self.publish(bridge_topic("devices"), devices, retain=True)

    def publish_event(self, event_type: str, data: dict) -> None:
        self.publish(bridge_topic("event"), {"type": event_type, "data": data})

    def publish_availability(self, device: Device, state: str) -> None:
        self.publish(availability_topic(device.friendly_name), {"state": state}, retain=True)

    def start(self) -> None:
        self.publish_state("online")
        self.publish_info()
        self.publish_devices()
        for device in self.devices.values():
            self.publish_availability(device, "online")

    # -- Zigbee -> MQTT ---------------------------------------------------

    def attribute_report(self, device: Device, cluster: str, attribute: str, raw: int) -> None:
        """A device reported a ZCL attribute; convert it and publish."""
        values = from_zigbee(cluster, attribute, raw)
        state = device.update_state(values)
        self.publish(device_topic(device.friendly_name), state)
        print(
            f"[z2m] {device.nwk}/1 {cluster}.{attribute}={raw} "
            f"-> {device.friendly_name} {json.dumps(values)}"
        )

    def command_received(self, device: Device, cluster: str, command: str) -> None:
        """A device sent a ZCL command to the coordinator, e.g. a button press."""
        values = {"action": command}
        state = device.update_state(values)
        self.publish(device_topic(device.friendly_name), state)
        print(
            f"[z2m] {device.nwk}/1 {cluster} command {command} "
            f"-> {device.friendly_name} {json.dumps(values)}"
        )

    # -- MQTT -> Zigbee ---------------------------------------------------

    def on_set(self, friendly_name: str, payload: dict) -> None:
        with self.lock:
            device = self.devices.get(friendly_name)
        if device is None:
            print(f"[z2m] set for unknown device {friendly_name!r}")
            return
        if "state" not in payload or "genOnOff" not in device.input_clusters:
            print(f"[z2m] {friendly_name} has nothing to set in {payload}")
            return

        # "TOGGLE" is a real ZCL command; the device works out the new value.
        command = {"ON": "on", "OFF": "off", "TOGGLE": "toggle"}.get(str(payload["state"]).upper())
        if command is None:
            print(f"[z2m] {friendly_name}: invalid state {payload['state']!r}")
            return
        print(f"[z2m] {friendly_name} {json.dumps(payload)} -> {device.nwk}/1 genOnOff command {command}")

        # The plug acts on it and reports its new onOff attribute back.
        was_on = device.state.get("state") == "ON"
        on = {"on": True, "off": False, "toggle": not was_on}[command]
        self.attribute_report(device, "genOnOff", "onOff", int(on))

    def on_permit_join(self, request: dict) -> None:
        transaction = request.get("transaction")
        seconds = request.get("time")
        if not isinstance(seconds, int) or not 0 <= seconds <= 254:
            response = {"data": {}, "status": "error", "error": "Invalid payload"}
        else:
            self.permit_join(seconds)
            response = {"data": {"time": seconds}, "status": "ok"}
        if transaction is not None:
            response["transaction"] = transaction
        self.publish(response_topic("permit_join"), response)

    def permit_join(self, seconds: int) -> None:
        """Open the network for `seconds` (0 closes it).

        A real coordinator broadcasts a Mgmt_Permit_Joining_req so that every
        router accepts association requests for that long.
        """
        if self.close_timer:
            self.close_timer.cancel()
        if seconds == 0:
            self.permit_join_end = None
            print("[z2m] permit_join closed")
        else:
            self.permit_join_end = int((time.time() + seconds) * 1000)
            print(f"[z2m] permit_join open for {seconds} s")
            self.close_timer = threading.Timer(seconds, self.permit_join, args=(0,))
            self.close_timer.daemon = True
            self.close_timer.start()
            if BUTTON.friendly_name not in self.devices:
                join_timer = threading.Timer(JOIN_DELAY_S, self.join_button)
                join_timer.daemon = True
                join_timer.start()
        self.publish_info()

    def join_button(self) -> None:
        """Pretend a new device joined and Zigbee2MQTT interviewed it."""
        if self.permit_join_end is None:
            return
        device = BUTTON
        ids = {"friendly_name": device.friendly_name, "ieee_address": device.ieee_address}
        print(f"[z2m] device {device.ieee_address} joined as {device.nwk}")
        self.publish_event("device_joined", ids)

        # The interview reads the node descriptor, the active endpoints, each
        # endpoint's clusters and genBasic's modelId, then matches a definition.
        self.publish_event("device_interview", {**ids, "status": "started"})
        time.sleep(1)
        self.publish_event(
            "device_interview",
            {
                **ids,
                "status": "successful",
                "supported": True,
                "definition": device.definition(),
            },
        )
        print(f"[z2m] interviewed {device.ieee_address}: {device.model}, clusters out {device.output_clusters}")

        with self.lock:
            self.devices[device.friendly_name] = device
        self.publish_devices()
        self.publish_availability(device, "online")

        time.sleep(PRESS_DELAY_S)
        self.command_received(device, "genOnOff", "toggle")


def from_zigbee(cluster: str, attribute: str, raw: int) -> dict:
    """Turn a raw ZCL attribute value into Zigbee2MQTT's JSON.

    A tiny stand-in for zigbee-herdsman-converters. The scaling comes from the
    ZCL specification, which is why it is the same for every vendor.
    """
    match cluster, attribute:
        case "msTemperatureMeasurement", "measuredValue":
            return {"temperature": raw / 100}  # int16, 0.01 °C
        case "msRelativeHumidity", "measuredValue":
            return {"humidity": raw / 100}  # uint16, 0.01 %
        case "genPowerCfg", "batteryPercentageRemaining":
            return {"battery": round(raw / 2)}  # uint8, 0.5 %
        case "genOnOff", "onOff":
            return {"state": "ON" if raw else "OFF"}
    raise ValueError(f"no converter for {cluster}.{attribute}")


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"[z2m] connection failed: {reason_code}")
        return

    print(f"[z2m] connected to {MQTT_HOST}:{MQTT_PORT}")
    client.subscribe([(set_topic(), 0), (request_topic("permit_join"), 0)])
    userdata["bridge"].start()
    userdata["connected"].set()


def on_message(client, userdata, msg):
    bridge: Bridge = userdata["bridge"]
    try:
        payload = json.loads(msg.payload)
    except ValueError:
        print(f"[z2m] not JSON on {msg.topic}: {msg.payload!r}")
        return

    if msg.topic == request_topic("permit_join"):
        bridge.on_permit_join(payload)
    elif msg.topic.endswith("/set"):
        friendly_name = msg.topic.removeprefix(device_topic("")).removesuffix("/set")
        bridge.on_set(friendly_name, payload)


def main() -> None:
    connected = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="zigbee2mqtt_mock")
    bridge = Bridge(client)
    client.user_data_set({"bridge": bridge, "connected": connected})
    client.on_connect = on_connect
    client.on_message = on_message

    # If the bridge dies, the broker publishes the offline state on its behalf.
    # A real Zigbee2MQTT does exactly the same.
    client.will_set(bridge_topic("state"), json.dumps({"state": "offline"}), retain=True)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    connected.wait()

    # The sensor reports its battery once, then temperature and humidity on a
    # timer -- the reporting interval a real device is configured with.
    bridge.attribute_report(SENSOR, "genPowerCfg", "batteryPercentageRemaining", 200)
    temperature, humidity = 2250, 5500
    try:
        while True:
            time.sleep(REPORT_INTERVAL_S)
            temperature += random.randint(-20, 20)
            humidity += random.randint(-50, 50)
            bridge.attribute_report(SENSOR, "msTemperatureMeasurement", "measuredValue", temperature)
            bridge.attribute_report(SENSOR, "msRelativeHumidity", "measuredValue", humidity)
    except KeyboardInterrupt:
        print("\n[z2m] stopping")
    finally:
        bridge.publish_state("offline")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
