# Hammerhead V3 HyperSpeed control protocol

This implementation targets USB `1532:0a61`, HID interface 3. It does not use
OpenRazer. Commands were traced through Razer's own product-2657 Synapse web
middleware, then ANC reads/writes and the source toggle were verified against the attached device.

## Evidence and scope

The locally installed Windows RazerAppEngine service-worker cache identified
these public Razer resources. They were fetched without running their code:

- [Product middleware](https://apps.razer.com/synapse/products/2657/mw/main.76d8255ea4b7ad8beddf.js)
  SHA-256 `e1dc5e231bb395e142938c0dd7f383d144427dd8d909fb5b51ac0040fb9bf45c`.
- [Input-source feature](https://apps.razer.com/synapse/products/2657/mw/3312.f89aeb0867efec42eeb6.js)
  SHA-256 `0723164273f927dee77215be8cd082256b60c1b7faabd2a6075caca4aaca60f0`.
- [Earbud hardware-event parser](https://apps.razer.com/synapse/products/2657/mw/rzHardwareEventsProtocol40ParserEarbuds.12960a3fa5ce52534f8b.js)
  SHA-256 `cbb868f190fdec6a5265ca8e517cca0d3766706a943c76d27dc854f77e6785a5`.

Line references below refer to the product middleware formatted with
Prettier 3.6.2. The proprietary source is not distributed with this project;
fetch the identified public resources to reproduce the analysis. Commands
were traced directly through the source and checked against the connected
hardware as detailed below.

## Transport

The product configuration selects `rzDevice40`, device type 3 (audio), report
ID 2, 64-byte reports, interface 3. The HID descriptor defines report 2 as a
feature report. Use HID `SET_FEATURE` and `GET_FEATURE`, not output writes.

Offsets in the complete 64-byte hidraw buffer, **including the report ID**:

| Offset | Meaning |
| --- | --- |
| 0 | Report ID `0x02` |
| 1 | Status: request `0`; response `2` means success |
| 2 | `(device_type << 5) | transaction_counter`, counter 1–31 |
| 3–4 | Zero for these fixed-length commands |
| 5–6 | Payload length, big endian |
| 7 | Command class |
| 8 | Command ID |
| 9 onward | Payload, zero-padded |
| 62 | XOR of bytes 3–61 |
| 63 | Reserved zero |

Match transaction ID, command class and command ID before accepting a reply.
Responses 0/1 mean pending/busy; 3 failed; 4 timed out; 5 unsupported. Do not
report success merely because the host accepted a write. Razer waits 100 ms
between sending and reading, then 50 ms between read attempts.

Evidence: product registration at line 139399; report setup at 49176;
transaction/checksum/report construction at 49217; send at 49508; receive and
validation at 49314. The Electron transport removes report ID before passing
the reply to the protocol parser, so its parser offsets are one lower.

## Commands

| Operation | Class | ID | Request payload | Expected response payload | Device type |
| --- | --- | --- | --- | --- | --- |
| Read ANC | `18` | `86` | `01` | profile, state, level | 3 |
| Set ANC | `18` | `06` | `01 state level` | profile, state, level | 3 |
| Toggle Bluetooth / HyperSpeed | `18` | `1d` | empty | inspect acknowledgement | 3 |
| Read earbud connections | `18` | `9a` | `01` | type, HyperSpeed status, Bluetooth status | **0** |

Hexadecimal values are shown above. ANC states: `00` off, `01` ANC,
`50` ambient. Keep the current level when changing state. The source defines
levels 0–10; the attached device initially returned level 10 with ANC off.

ANC command encoding and parsing: lines 45016–45064 and 45470–45479; state
enumeration: line 45576. The feature calls profile 1 at 75500. Source toggle
constant: 46804, implementation: 46521. The product's lazy input-source feature
calls `switchAudioConnectionMode`; it does **not** use the generic
`setAudioSource` API bundled for other products.

Connection read: 46526–46550 and 116157. Its helper explicitly overrides the
transaction's device type to 0. Connection type 1 means earbuds; each status
is 0 disconnected, 1 left only, 2 right only, 3 both connected (46970).

## Notifications

Input report 5 carries notification records. The next byte identifies the
event: `0x21` ANC change, `0x31` battery change, `0x38` connection change.
Payloads are respectively `[state]`, `[left_percent, right_percent]`, and
`[type, hyperspeed_status, bluetooth_status]`. See `events.pretty.js:55` and
middleware constants at 53174, 53275–53284. This documents the parser; receiving
these notifications on Linux must be validated separately.

## Pairing and Bluetooth limitations

No model-specific software command to enter **Bluetooth discoverable pairing
mode** was established. Shared-library `setDevicePairingMode` and
`setDeviceAutoPairingMode` methods exist, but their presence does not establish
Hammerhead support or equivalence to the pairing gesture. They must not be
exposed as working controls or probed by sending guessed commands.

The [official manual, page 17](https://dl.razerzone.com/master-guides/RazerSynapse4/HAMMERHEADV3HYPERSPEED-00002657-en.pdf)
states that Synapse configuration is unavailable after switching to Bluetooth.
Returning to HyperSpeed through the dongle has not been established by static
analysis. Do not promise a software round trip; the earbud gesture may be
needed to restore the control connection.

## Observed device validation

The application's developer read ANC successfully using the above frame:
request prefix `02 00 61 00 00 00 01 18 86 01`, response prefix
`02 02 61 00 00 00 03 18 86 01 00 0a`. Response means profile 1, ANC off,
level 10. This validates transport and ANC read on this device, not every
command in the table. Keep subsequent end-to-end validation separate from
the static protocol derivation.

### Completed hardware checks

- Set ANC on, ambient, and off; each was confirmed by a fresh ANC query.
- Native KDE GUI clicks changed ambient and off with device readback.
- Original state (off, level 10) restored.
- Source toggle acknowledged; the control link subsequently returned empty
  feature reports. The user confirmed Bluetooth switching and used the gesture
  to return to HyperSpeed. Connection read then reported both earbuds on
  HyperSpeed (`01 03 00`), and ANC read returned off again.
- Empty 64-byte feature responses mean no available response; they never
  count as success.

These checks cover this attached device and firmware only. No firmware update,
factory reset, dongle re-pairing, or Bluetooth-discoverability command was sent.
