# zigbee-examples

Small, self-contained experiments for getting familiar with
[Zigbee](https://csa-iot.org/all-solutions/zigbee/) and the software around it.
Each directory is a uv project.

Zigbee is a specification, not a product, and it says nothing about how a
gateway talks to a backend. These examples use
[Zigbee2MQTT](https://www.zigbee2mqtt.io/) as the gateway and fake everything
below one of its interfaces — so you can work at that layer without hardware.

```
  [ backend application ]
           ▲ MQTT (JSON)                   ← hello: fakes everything below this
  [ Zigbee2MQTT ] (Node.js)
     zigbee-herdsman: ZDO, ZCL, interview
     zigbee-herdsman-converters: ZCL ↔ JSON
           ▲ serial (Z-Stack MT / EZSP / …) ← not built yet
  [ coordinator dongle / NCP firmware ]
     APS, NWK, MAC
           ▲ IEEE 802.15.4, 2.4GHz
  [ routers / end devices ]
```

## Examples

| Name | Fakes | Description |
|---|---|---|
| [hello](hello/) | everything below MQTT | A backend app and a fake Zigbee2MQTT: discovery, joining, sensor reports and switching a plug |

## Next steps

- [ ] Emulate a coordinator's serial protocol (TI Z-Stack's MT/ZNP or Silicon
  Labs' EZSP) on a pseudo-terminal, so the real Zigbee2MQTT or zigpy runs
  without a dongle.

## How to run

This repo uses [uv](https://docs.astral.sh/uv/). Enter an example directory and
follow its README.

```bash
cd hello
uv sync
```

The broker binds port 1883, the same as
[wirepas-examples](https://github.com/gkuga/wirepas-examples); run one at a
time.

## Notes on Zigbee

- **A standard with many stacks.** Zigbee comes from the Connectivity Standards
  Alliance. TI (Z-Stack), Silicon Labs (EmberZNet), NXP and others ship their
  own stacks; devices interoperate over the air and in the Zigbee Cluster
  Library, not in any host-side API.
- **Three roles.** One *coordinator* forms the network (channel, PAN ID,
  network key). *Routers* are mains powered and relay. *End devices* are
  usually battery powered, sleep, and talk only through their parent router.
- **Addressing in layers.** A 64-bit IEEE address names the device, a 16-bit
  network address is assigned at join, an endpoint (1–240) picks an
  application on the device, and a cluster picks the function on that
  endpoint.
- **The ZCL is the shared vocabulary.** Clusters define attributes, commands
  and units, so a temperature from any vendor is a signed 16-bit value in
  0.01 °C. Vendors still add their own clusters and quirks, which is why
  Zigbee2MQTT carries a per-model converter database.
- **No gateway standard.** Zigbee2MQTT, Home Assistant's ZHA (built on
  [zigpy](https://github.com/zigpy/zigpy)), deCONZ and vendor hubs all expose
  something different above the coordinator. Zigbee2MQTT is used here because
  its API is MQTT, as with Wirepas.

## Zigbee, Wirepas and ZETA

Compared with [wirepas-examples](https://github.com/gkuga/wirepas-examples)
and [zeta-examples](https://github.com/gkuga/zeta-examples):

| | Zigbee (via Zigbee2MQTT) | Wirepas | ZETA |
|---|---|---|---|
| Radio | IEEE 802.15.4, 2.4GHz | 2.4GHz, own stack | 920MHz UNB |
| Multi-hop | routers relay, end devices don't | every node routes | dedicated Motes relay |
| Specification | open standard, many vendors | one vendor | one vendor |
| Where the network ends | your gateway, publishing to MQTT | your gateway, publishing to MQTT | the vendor's ZETA Server |
| Application API | MQTT + JSON, pushed | MQTT + protobuf, pushed | HTTP + JSON, polled |
| Payload meaning | standard ZCL clusters | endpoints, agreed by both ends | opaque hex |
| Device discovery | `bridge/devices` with capabilities | none, addresses are known | module list |
| Request correlation | `transaction` in the payload | `req_id` in the payload | `msgid`, not in the history |
| Host-side stack | ZDO, ZCL, interview, converters | practically nothing | none, the server is closed |

The last row is the biggest difference. A Wirepas dongle does nearly
everything and the host only frames commands. A Zigbee coordinator dongle
stops below the application layer: the host still has to interview devices,
encode and decode ZCL frames, and know each model's quirks. That is what
Zigbee2MQTT is, and why faking it in hello means faking a small slice of ZCL.

## References

- Zigbee2MQTT, MQTT topics and messages —
  [docs](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html).
  The source for every topic and payload in hello.
- Zigbee2MQTT, exposes —
  [docs](https://www.zigbee2mqtt.io/guide/usage/exposes.html).
- [Koenkk/zigbee-herdsman](https://github.com/Koenkk/zigbee-herdsman) and
  [Koenkk/zigbee-herdsman-converters](https://github.com/Koenkk/zigbee-herdsman-converters) —
  the cluster names (`genOnOff`, `msTemperatureMeasurement`, …) used in hello.
- Zigbee Cluster Library specification, Connectivity Standards Alliance.
