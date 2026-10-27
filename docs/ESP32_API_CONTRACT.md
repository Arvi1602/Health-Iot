# ESP32 Integration Contract

This documents the existing HealthGuard API, not firmware. The Python simulator
and future ESP32 are interchangeable HTTP ingestion clients. No hardware-only
endpoint, device registration, or new JSON fields are required.

## Hardware and planned signal wiring

| Sensor | Measurement / JSON field | ESP32 connection | Protocol |
| --- | --- | --- | --- |
| MAX30102 | Derived heart rate → `heart_rate`; derived oxygen saturation → `spo2` | SDA → GPIO 21; SCL → GPIO 22 | I²C |
| DS18B20 | Temperature in Celsius → `temperature_c` | DATA → GPIO 4 | One-Wire |

These GPIO assignments are the planned project mapping, not universal board
defaults or a complete power/pull-up wiring guide. Check the actual module's
electrical requirements before wiring it.

MAX30102 supplies optical PPG measurements from which the host derives heart rate
and SpO₂; it does not measure ECG. See the manufacturer's
[MAX30102 documentation](https://www.analog.com/en/products/max30102.html).
DS18B20 supplies digital Celsius temperature over a One-Wire interface; see its
[datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ds18b20.pdf).
The [TASK-021 firmware](../firmware/healthguard_esp32/README.md) uses the library's
algorithm; physical hardware validation is still pending.

## Network and endpoint

```text
Method:       POST
URL:          http://<HEALTHGUARD_SERVER_IP>:8000/api/readings
Content-Type: application/json
```

Replace `<HEALTHGUARD_SERVER_IP>` with the computer's IP/hostname reachable from
the ESP32. For a typical demonstration, connect both to the same Wi-Fi/LAN, or
use another routable network. The server must be reachable on TCP port 8000.
`localhost` and `127.0.0.1` on the ESP32 refer to the ESP32 itself, not the laptop.

Start locally for computer-only testing:

```bash
.venv/bin/python -m app.seed
.venv/bin/python -m uvicorn app.main:app --reload
```

For a later trusted-LAN test, bind the server to its network interfaces:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`0.0.0.0` is a **bind address**, not the destination to put in the ESP32 URL.
Use the laptop's actual LAN IP. `192.168.1.100` below is illustrative only.
TASK-020 verification uses loopback; it does not verify a physical ESP32 or LAN.

## Request fields and validation

Send **one JSON object for one patient's measurement snapshot per POST**, not an
array. Use the exact field names below. The authoritative implementation is
[`ReadingCreate`](../app/schemas.py) and [`create_reading`](../app/readings.py).

| Field | Pydantic type / JSON representation | Required | Meaning and validation |
| --- | --- | --- | --- |
| `patient_id` | strict `int` / integer | Yes | Existing patient database ID; 1–9223372036854775807 inclusive |
| `heart_rate` | strict `int` / integer | Yes | Beats per minute; 1–300 inclusive |
| `spo2` | strict `float` / number | Yes | Percentage; 0–100 inclusive, finite |
| `temperature_c` | strict `float` / number | Yes | Celsius; 20–50 inclusive, finite |
| `recorded_at` | `datetime \| None` / ISO-8601 string or null | No | Measurement time; defaults as described below |

JSON integer numbers are accepted for `spo2` and `temperature_c` as well as decimal
numbers. Numeric strings and booleans are rejected; integer fields also reject
decimal-form numbers such as `78.0`. Required fields cannot be null or omitted.
Non-finite numbers, malformed JSON and unknown fields are rejected with 422.
Do not send `device_id`, `doctor_id`, `patient_name`, `timestamp`, `heartRate`,
`oxygen`, `temp`, `alert`, or other undocumented fields.

Use percentage `98` or `98.0`, not fraction `0.98`. The latter is numerically
within validation bounds but means **0.98 percent**, not 98 percent. Send Celsius;
convert Fahrenheit before submission. These are **API sanity bounds, not clinical
alert thresholds**. Send measured values only; do not evaluate demo alerts on the
ESP32. Configurable academic rules remain centralized on the backend and are
not clinically validated or suitable for medical decision-making.

`patient_id` must exist. Patient names cannot replace it and ingestion never
creates a patient. Find the actual ID from the dashboard or the database lookup
in [README's simulator instructions](../README.md#sensor-simulator). ID 1 in these
examples was verified in an isolated seeded database; do not assume it elsewhere.

## Examples

Without a device timestamp:

```json
{
  "patient_id": 1,
  "heart_rate": 78,
  "spo2": 98.0,
  "temperature_c": 36.8
}
```

The HTTP request has this form (the HTTP client supplies body framing):

```http
POST /api/readings HTTP/1.1
Host: 192.168.1.100:8000
Content-Type: application/json

{"patient_id":1,"heart_rate":78,"spo2":98.0,"temperature_c":36.8}
```

Developer curl example, run on the computer hosting FastAPI. Replace ID 1 with
your verified patient ID. From another computer or ESP32, replace the loopback
host with the reachable server LAN address.

```bash
curl --fail-with-body -i -X POST \
  http://127.0.0.1:8000/api/readings \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":1,"heart_rate":78,"spo2":98.0,"temperature_c":36.8}'
```

With a measurement timestamp:

```json
{
  "patient_id": 1,
  "heart_rate": 78,
  "spo2": 98.0,
  "temperature_c": 36.8,
  "recorded_at": "2026-10-08T14:30:00Z"
}
```

### Timestamp behavior

Prefer a full ISO-8601 datetime with UTC `Z`. The current parser uses Python's
`datetime.fromisoformat` (with `Z` converted to an offset); it also accepts naive
datetimes and date-only strings. A naive datetime is interpreted as UTC; a
date-only value means midnight UTC. Offset-bearing timestamps are converted to
UTC, so `2026-10-08T20:00:00+05:30` returns `2026-10-08T14:30:00Z`.
Numeric Unix epochs and numeric epoch strings are rejected.

Omitting `recorded_at` or sending null uses SQLite's current UTC timestamp at
insertion (`server_default=func.now()`), with second precision. That is the server's
insertion time, not an independently known sensor capture time. Supplied fractional
seconds are retained up to Python datetime's microsecond precision. SQLite stores
UTC without timezone metadata; API responses serialize UTC with `Z`.

Malformed/impossible dates return 422. There is no current age/future-time limit.
An old timestamp remains old even when submitted now; dashboard freshness uses
that recorded timestamp. If the ESP32 has reliable synchronized time (for example,
NTP), it may send it. Otherwise omit it for the demo; no NTP/RTC implementation is
required here.

## Responses and retry guidance

Success is **HTTP 201 Created**, using the existing `ReadingResponse`:

```json
{
  "id": 2,
  "patient_id": 1,
  "heart_rate": 78,
  "spo2": 98.0,
  "temperature_c": 36.8,
  "recorded_at": "2026-10-08T14:30:00Z"
}
```

This timestamped example was tested after one timestamp-free insertion in an
isolated seeded database; IDs and default timestamps depend on the database/run.
The backend validates, looks up the patient, prepares the Reading and evaluates
the centralized demo rules, then commits Reading and generated Alerts atomically.
Only after commit does it broadcast one `reading` event to connected authorized
patient subscribers. No alert data is added to this REST response and no `alert`
WebSocket event is emitted. Live delivery is best effort: a 201 confirms persistence,
not that a browser received the event.

| Result | Meaning / client action |
| --- | --- |
| 201 | Accepted; continue with the next measurement |
| 422 | Invalid payload; correct fields/types/values instead of retrying indefinitely |
| 404 | Patient not found; check configured patient ID |
| 500 | Submission failed, e.g. persistence failure; retry later with bounded delay |
| Network failure/timeout | Outcome may be unknown; log it and avoid tight retry loops |

A rejected 422 or unknown-patient 404 creates no Reading, no Alerts and no reading
broadcast. Persistence failure rolls back the transaction. Error messages remain
generic; do not depend on raw database details. Other 4xx responses should be
investigated as request/configuration problems.

There is **no idempotency key or duplicate-submission protection** in ingestion.
A timeout may occur after commit; retrying the same snapshot can create another
Reading and more Alerts. Do not treat retries as exactly-once delivery. Use a
bounded delay/attempt policy for future firmware, not an infinite tight loop or
an elaborate queue. The current simulator stops on failure and does not retry.

Tested invalid example (422):

```json
{"patient_id":1,"heart_rate":-5,"spo2":98.0,"temperature_c":36.8}
```

Also rejected: replacing `spo2` with `150`, or setting `recorded_at` to
`"not-a-date"`. For a 404 test use the same valid payload with a patient ID verified
absent from the target database; no fixed ID is universally nonexistent.

## Request pseudocode — not firmware

```text
read MAX30102 optical samples
derive heart rate and SpO₂ values
read DS18B20 Celsius temperature
build one JSON object using the exact documented field names
include recorded_at only when reliable measurement time is available
HTTP POST to the reachable HealthGuard /api/readings URL as application/json
if status is 201: record success
otherwise: log failure and apply the simple response guidance above
```

A 1–2 second POST cadence is suitable as an illustrative software demo cadence
(the simulator defaults to two seconds), not a clinical sampling requirement or
a specification of the sensors' internal sampling rate.

## Security and end-to-end flow

The sensor endpoint intentionally has **no device authentication or doctor-login
requirement**. A client that can reach it can submit readings for an existing
patient. Use current HTTP only on a trusted local academic demo network; do not
describe it as production-secure. Future deployment needs device authentication,
TLS/HTTPS and stronger network security. Doctor dashboard/history/alerts and
WebSocket access remain separately authenticated and ownership-protected.

```text
MAX30102 ── I²C ──┐  → derived heart_rate + spo2
                  ├─ ESP32 → JSON / HTTP POST /api/readings
DS18B20 ─ One-Wire┘  → temperature_c
                                ↓
                    validation + patient lookup
                                ↓
                 Reading + backend demo rule evaluation
                                ↓
                  atomic SQLite Reading + Alert commit
                                ↓
                    reading WebSocket event
                                ↓
                 authenticated doctor dashboard
                 cards / charts / alerts / history
```

The Python simulator currently occupies the ESP32's HTTP-client position; all
downstream behavior stays the same. This document adds no firmware, algorithms,
MQTT, device authentication, API fields, or frontend functionality.
