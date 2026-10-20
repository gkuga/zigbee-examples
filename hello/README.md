# hello

A Zigbee "Hello World" that runs **without any hardware**.

Zigbee itself defines no gateway API, so this example uses the most widely used
open-source one: [Zigbee2MQTT](https://www.zigbee2mqtt.io/). It ends at an MQTT
broker, and everything above that line speaks its
[MQTT API](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html)
(JSON over MQTT). So a backend application can be written and tested against a
fake Zigbee2MQTT that publishes the very same messages a real one would.

```
┌──────────────────────────────────────────────────────────────┐
│ Real deployment                      │ This example          │
│                                      │                       │
│  [ backend application ]             │  app.py               │
│           ▲                          │      ▲                │
│           │ MQTT (JSON)              │      │ MQTT (JSON)    │
│           ▼                          │      ▼                │
│  [ MQTT broker ]                     │  Mosquitto (Docker)   │
│           ▲                          │      ▲                │
│           │                          │      │                │
│  [ Zigbee2MQTT ] (Node.js)           │      │                │
│     zigbee-herdsman + converters     │      │                │
│           ▲                          │      │  zigbee2mqtt_mock.py
│           │ serial (Z-Stack / EZSP)  │      │  fakes all of  │
│  [ coordinator dongle / NCP FW ]     │      │  this          │
│           ▲                          │      │                │
│           │ IEEE 802.15.4, 2.4GHz    │      │                │
│  [ routers / end devices ]           │      ▼                │
└──────────────────────────────────────────────────────────────┘
```

`app.py` is the part you keep when real hardware arrives: it only talks MQTT
and never touches the serial link or the dongle.

## Run it

Three terminals, in this order.

```bash
# 1. MQTT broker
docker compose up -d

# 2. the backend application (start it first so it sees every message)
uv sync
uv run app.py

# 3. the fake Zigbee2MQTT
uv run zigbee2mqtt_mock.py
```

`app.py` prints something like:

```
[app] connected to localhost:1883
[app] bridge is online
[app] permit_join #1 sent: {'time': 30}
[app] network: channel 11, PAN ID 0x1a62, coordinator zStack3x0
[app] permit_join is closed
[app] device Coordinator: Coordinator, 0x00124b0018e2a0f1 / 0x0000, - -
[app] device hello_sensor: EndDevice, 0x00158d0001a2b3c4 / 0x6f3c, Example HELLO-TH
[app] device hello_plug: Router, 0x0017880100aabbcc / 0x4c21, Example HELLO-PLUG
[app] set hello_plug {'state': 'ON'}
[app] hello_sensor is online
[app] hello_plug is online
[app] hello_sensor: {"battery": 100, "linkquality": 120}
[app] permit_join is open
[app] permit_join #1 -> ok {'time': 30}
[app] hello_plug: {"state": "ON", "linkquality": 220}
[app] event device_joined: 0x00124b0001ddeeff
[app] event device_interview (started): 0x00124b0001ddeeff
[app] event device_interview (successful): 0x00124b0001ddeeff
[app] device 0x00124b0001ddeeff: EndDevice, 0x00124b0001ddeeff / 0x9a07, Example HELLO-BTN
[app] 0x00124b0001ddeeff is online
[app] hello_sensor: {"battery": 100, "linkquality": 120, "temperature": 22.43}
[app] hello_sensor: {"battery": 100, "linkquality": 120, "temperature": 22.43, "humidity": 55.17}
[app] 0x00124b0001ddeeff: {"action": "toggle", "linkquality": 95}
[app] set hello_plug {'state': 'TOGGLE'}
[app] hello_plug: {"state": "OFF", "linkquality": 220}
```

and `zigbee2mqtt_mock.py` shows what happened below the API:

```
[z2m] 0x6f3c/1 genPowerCfg.batteryPercentageRemaining=200 -> hello_sensor {"battery": 100}
[z2m] permit_join open for 30 s
[z2m] hello_plug {"state": "ON"} -> 0x4c21/1 genOnOff command on
[z2m] 0x4c21/1 genOnOff.onOff=1 -> hello_plug {"state": "ON"}
[z2m] device 0x00124b0001ddeeff joined as 0x9a07
[z2m] interviewed 0x00124b0001ddeeff: HELLO-BTN, clusters out ['genOnOff']
[z2m] 0x6f3c/1 msTemperatureMeasurement.measuredValue=2243 -> hello_sensor {"temperature": 22.43}
[z2m] 0x9a07/1 genOnOff command toggle -> 0x00124b0001ddeeff {"action": "toggle"}
```

Stop the broker with `docker compose down`.

## What happens

All topics start with the base topic, `zigbee2mqtt` by default.

| Direction | Topic | Message |
|---|---|---|
| bridge → backend | `bridge/state` | `{"state": "online"}` — **retained**. The MQTT last will publishes `offline` if the bridge dies. |
| bridge → backend | `bridge/info` | Channel, PAN ID, coordinator type, `permit_join` — retained, republished whenever it changes. |
| bridge → backend | `bridge/devices` | Every device: addresses, type, endpoints and clusters, and a `definition` whose `exposes` says what the device can do — retained. |
| backend → bridge | `bridge/request/permit_join` | `{"time": 30, "transaction": 1}` — open the network for joining. |
| bridge → backend | `bridge/response/permit_join` | `{"data": {"time": 30}, "status": "ok", "transaction": 1}` |
| bridge → backend | `bridge/event` | `device_joined`, then `device_interview` `started` / `successful`. |
| bridge → backend | `<friendly_name>` | The device's state as JSON: `{"temperature": 22.43, ...}`. |
| bridge → backend | `<friendly_name>/availability` | `{"state": "online"}` — retained. |
| backend → bridge | `<friendly_name>/set` | `{"state": "ON"}`, `{"state": "TOGGLE"}` |

Details worth noticing:

- **The backend knows no device in advance.** Unlike the Wirepas hello, where
  both ends share a node address and endpoints, `app.py` learns the devices
  from `bridge/devices` and decides what to do from `exposes`: anything with a
  `switch` gets turned on, any `toggle` action toggles every switch.
- **Two addresses per device.** The 64-bit IEEE address is burned in at the
  factory and never changes. The 16-bit network address (`0x6f3c`) is handed
  out when the device joins and is what actually goes over the air; it can
  change on a rejoin. The coordinator is always `0x0000`.
- **Endpoints and clusters** are where the meaning lives. A cluster is a
  standard bundle of attributes and commands from the Zigbee Cluster Library
  (ZCL): `genOnOff`, `msTemperatureMeasurement`, … Like Wirepas endpoints they
  say how to read the payload, but here the vocabulary is standardized, not
  agreed between your two ends.
- **Units come from the ZCL.** The sensor reports `measuredValue=2243` in
  0.01 °C, and battery in 0.5 % steps (`200` = 100 %). Converting that to
  `{"temperature": 22.43}` is the job of Zigbee2MQTT's converters, and the
  mock's `from_zigbee` reproduces just enough of it.
- **Input vs output clusters.** The plug *serves* `genOnOff` (input cluster):
  it holds the `onOff` attribute and obeys commands. The button *uses*
  `genOnOff` (output cluster): it has no state, it sends a `toggle` command.
  Zigbee2MQTT turns a received command into an `action`.
- **The button could drive the plug without any of this.** Here `app.py` relays
  the button press, but Zigbee lets you *bind* the button's output cluster to
  the plug's input cluster, and then the command goes device to device without
  the coordinator, the broker or the backend.
- **Joining is a two-step thing.** `permit_join` lets a device in; the
  *interview* then reads its endpoints, clusters and `genBasic` model id and
  looks up a definition. Only after that does it appear in `bridge/devices`
  with `exposes`.
- **The state is cached and merged.** Each message carries the whole known
  state, so a humidity report still includes the last temperature.
- **`linkquality` is the LQI of the last hop only.** Unlike Wirepas there is
  no hop count or travel time; the route is the network layer's business.
- **`transaction` is not in the topic.** A response is matched to its request
  by the value echoed back in the payload, just like Wirepas' `req_id`.
- The retained `bridge/state` survives a restart of the subscriber, so on the
  second run you may see a stale `offline` before the fresh `online`.

## Files

| File | Role |
|---|---|
| [app.py](app.py) | The backend application — hardware-independent. |
| [zigbee2mqtt_mock.py](zigbee2mqtt_mock.py) | Fake Zigbee2MQTT: fakes the devices, the coordinator and Zigbee2MQTT. |
| [common.py](common.py) | Broker settings and topic helpers shared by both. |
| [compose.yaml](compose.yaml) | Mosquitto broker on `localhost:1883`, anonymous access. |

`MQTT_HOST`, `MQTT_PORT` and `Z2M_BASE_TOPIC` override the defaults, e.g. to
point `app.py` at a real Zigbee2MQTT:

```bash
MQTT_HOST=192.168.1.10 uv run app.py
```

Careful: against a real network it opens joining for 30 s and switches on
every switch it finds.

## Dependencies

- [`paho-mqtt`](https://pypi.org/project/paho-mqtt/) — the MQTT client.

The payloads are plain JSON, so there is no message library to install.

## What the mock does not do

- Only the topics above. The real API also has groups, bindings, OTA updates,
  `/get`, device renaming and removal, and many more `bridge/request/...`
  commands.
- No sleepy-device behaviour: a real end device only hears the network when it
  polls its parent, so a `/set` or `/get` sent to the sensor would wait or time
  out.
- The devices, vendor and models are made up, and the network is three
  devices with a fixed link quality.
- `bridge/info` leaves out the config, config schema and version details.
- Friendly names containing `/` are allowed by Zigbee2MQTT and would break
  `app.py`'s topic parsing; a real backend matches against the names from
  `bridge/devices`.
