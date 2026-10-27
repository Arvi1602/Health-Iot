# HealthGuard ESP32 prototype

**Implementation prepared; physical verification pending. TASK-021 is not complete.**

Physical verification is deferred at the user's request (2026-10-11). The current
demo/testing workflow uses software sample readings through the existing API;
the upload and sensor procedures below are future reference only.

Target: an ESP32-WROOM-32 development board (`esp32dev`, classic dual-core ESP32).
Actual board, MAX30102 breakout markings/supply requirements, and DS18B20
module/probe have not yet been identified or physically tested. No USB serial
ESP32 was visible during preparation. Do not interpret compilation or simulator
success as evidence of sensor operation.

## Wiring and power verification before uploading

| Signal | ESP32 GPIO | Interface |
| --- | --- | --- |
| MAX30102 SDA | 21 | I²C |
| MAX30102 SCL | 22 | I²C |
| DS18B20 DATA/DQ | 4 | One-Wire |

ESP32 GPIO uses 3.3 V logic. Identify the actual MAX30102 breakout and consult
its board documentation for VIN, regulators, level shifting and I²C pull-ups.
Breakout power requirements vary; a bare MAX30102 must not simply be connected to
5 V. The driver probes address 0x57; its part-ID check also matches MAX30105, so
software detection does not establish the actual sensor model. Inspect markings.

For a bare DS18B20, the manufacturer's externally powered circuit uses a 4.7 kΩ
DATA pull-up. Use a 3.3 V-compatible supply/pull-up arrangement and common ground;
verify whether your module already includes the resistor. Follow its actual
pinout, not assumed probe wire colors. This firmware requires externally powered
DS18B20 operation and rejects parasite-power mode. See the
[DS18B20 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ds18b20.pdf)
and [MAX30102 documentation](https://www.analog.com/en/products/max30102.html).

Record actual board/module names, supply connections and resistor arrangement
in the physical verification record below before proceeding. This is not a
complete wiring approval for an unidentified breakout.

## Build environment and pinned dependencies

Use PlatformIO Core with the checked-in `platformio.ini`:

| Component | Version / target |
| --- | --- |
| PlatformIO Core used for compilation | 6.2.0 |
| PlatformIO Espressif32 platform | 6.12.0 |
| Arduino-ESP32 framework supplied by that platform | 2.0.17 |
| Board | `esp32dev` (ESP32-WROOM-32 development board) |
| SparkFun MAX3010x Pulse and Proximity Sensor Library | 1.1.2 |
| OneWire (Paul Stoffregen) | 2.3.8 |
| DallasTemperature (Miles Burton) | 3.11.0 |
| WiFi, HTTPClient, Wire, FreeRTOS | Included with the ESP32 framework |

Compile verification on this workspace: **passed** for the final stage-3
`compile_check` environment, with placeholder configuration only. Arduino package
`3.20017.241212+sha.dcc1105b`, Xtensa GCC `8.4.0+2021r2-patch5`; RAM 47,916 bytes
(14.6%), flash 819,713 bytes (62.5%). This is not an upload or physical result.
The pinned upstream libraries emit non-blocking `I2C_BUFFER_LENGTH` redefinition
(SparkFun/Wire) and extra-token `#undef` warnings (OneWire). They were not patched
locally; the complete firmware linked successfully.

The SparkFun `MAX30105` class supports MAX30102 in red/IR mode. Its bundled
Maxim algorithm supplies heart-rate and SpO₂ validity flags. Acquisition follows
the rate/window configuration of
[SparkFun's SpO₂ example](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/blob/master/examples/Example8_SPO2/Example8_SPO2.ino).
Algorithm source/licenses remain in the installed library; no sensor algorithm
has been copied into this repository. See also the
[PlatformIO release](https://github.com/platformio/platform-espressif32/releases/tag/v6.12.0)
and [DallasTemperature library](https://github.com/milesburton/Arduino-Temperature-Control-Library).

From the repository root, with `pio` installed:

```bash
# Compile the full HTTP-enabled code with placeholders, without real secrets.
pio run -d firmware/healthguard_esp32 -e compile_check

# Create local configuration once; do not overwrite an existing secrets.h.
cp -n firmware/healthguard_esp32/secrets.h.example firmware/healthguard_esp32/secrets.h
```

Edit `secrets.h` locally. It is Git-ignored, as are `.pio` artifacts (which can
contain compiled credentials). Never share a real secrets file or firmware binary
built with credentials. The placeholder `compile_check` build must not be used
for physical testing. It compiles stage 3, but placeholder URL validation prevents
HTTP operation.

Configure Wi-Fi SSID/password, the full reachable server URL ending `/api/readings`,
and a verified patient ID. No password is printed. The firmware does not print
the SSID or server URL; it prints its assigned IP, submitted measurements, and
HTTP status. The URL must not contain credentials; use a plain trusted-LAN host.

## Staged physical verification

Do not advance to the next stage until the current stage succeeds physically.

1. **Detection:** leave `HEALTHGUARD_STAGE=1`. Compile/upload to the correct port
   and check Serial at 115200 baud. Both sensors must be found. Firmware then
   deliberately stops; it never connects Wi-Fi or sends data in this stage.
2. **Measurement:** set stage 2, rebuild/upload. Check actual derived PPG heart
   rate/SpO₂ and prototype Celsius temperature over Serial. Invalid results are
   skipped. There is still no Wi-Fi/HTTP. Fix sensor contact/wiring before stage 3.
3. **Integration:** set stage 3 only after both prior stages pass. Configure the
   server, stop the Python simulator, and run the physical-only procedure below.

```bash
pio device list
pio run -d firmware/healthguard_esp32 -e esp32dev
# Replace the placeholder with the actual USB serial port identified above.
pio run -d firmware/healthguard_esp32 -e esp32dev -t upload --upload-port <SERIAL_PORT>
pio device monitor -b 115200 -p <SERIAL_PORT>
```

Do not upload to Bluetooth/debug-console ports. Some development boards require
their BOOT button during upload; follow your board's instructions. No upload was
attempted without a verified connected board.

Expected log *patterns*, not observed physical results:

```text
ESP32 booted — HealthGuard academic prototype
MAX30102-compatible device found (confirm actual module marking)
DS18B20 found
Sensor HR=<calculated> bpm SpO2=<calculated> % Temp=<measured> C
Wi-Fi connected. IP: <ESP32 LAN IP>
POST /api/readings payload: <actual JSON>
HTTP 201
Reading accepted (<count>)
```

## Measurement and submission behavior

The sensor produces optical PPG, not ECG. Red+IR acquisition is configured at
100 samples/s with averaging by four: 25 FIFO samples/s. The algorithm uses a
100-sample (~4 second) window, recalculated after 25 new samples (~1 second).
The algorithm's valid flags and API sanity bounds must pass; no fake/clamped
measurements replace invalid results. Temperature conversion is asynchronous,
12-bit/750 ms, with disconnected, 85°C startup, non-finite and API-out-of-range
results rejected. A complete valid snapshot needs a temperature at most two
seconds old. API sanity bounds are not medical alert thresholds.

The acquisition loop services the small driver FIFO frequently. A servicing gap
over 100 ms or missing optical samples over 500 ms discards the window and starts
collection again rather than calculating over lost samples. Sampling behavior
under real hardware load still needs physical verification.

HTTP runs in a separate FreeRTOS task on core 0, using a one-slot latest-value
mailbox. It sends no more often than every two seconds and discards unsent
snapshots older than 1.5 seconds. Sampling continues during bounded HTTP timeouts.
There is no offline queue, replay, NTP or `recorded_at`; HealthGuard supplies the
insertion timestamp. The JSON has exactly `patient_id`, `heart_rate`, `spo2`, and
`temperature_c` as numbers; temperature is intentionally serialized to two decimals.
Serial payload output allows exact comparison with persistence/UI formatting.

Wi-Fi reconnect attempts are spaced ten seconds apart. HTTP 201 counts as
accepted; 3xx/4xx stops submissions for configuration correction/reset. Network,
5xx or unexpected statuses wait five, then ten seconds before attempting a **new
fresh snapshot**; three consecutive failures stop HTTP until reset. There is no
resend of an ambiguous snapshot because ingestion is not idempotent: a timeout
can occur after commit. Check the database if counts disagree.

`HEALTHGUARD_MAX_ACCEPTED=10` stops HTTP after ten 201 responses while sampling
continues. Reset the board to resume another window. Set zero only for a continuous
demo. A 1–2 second cadence is a software demonstration target, not a clinical
sampling requirement; valid data availability governs actual submissions.

## Physical-only end-to-end procedure

1. Stop all simulators targeting this patient. Verify sensor stages 1 and 2.
2. Seed/select an actual patient and configure the same ID in `secrets.h`.
3. Start FastAPI on the trusted demo LAN:

   ```bash
   .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   curl --fail-with-body -i http://127.0.0.1:8000/health
   ```

   Use the computer's actual LAN IP in the ESP32 URL, not `0.0.0.0`, `localhost`,
   or `127.0.0.1`. Both must share Wi-Fi/LAN or a routable network. Allow incoming
   TCP 8000 for this application/demo network if required; do not disable the
   firewall globally. No LAN/firewall setting was changed during preparation.
4. Log in normally, select the configured patient, and confirm WebSocket Connected.
   In browser developer tools, open Network → the patient WebSocket → Messages.
5. Before powering stage 3, record the patient's row count and maximum ID using
   SQLAlchemy (replace ID 1 with the verified ID):

   ```bash
   .venv/bin/python - <<'PY'
   from sqlalchemy import select, func
   from app.database import SessionLocal
   from app.models import Reading
   patient_id = 1  # Replace with actual configured patient ID.
   with SessionLocal() as db:
       print(db.execute(select(func.count(Reading.id), func.max(Reading.id)).where(
           Reading.patient_id == patient_id)).one())
   PY
   ```
6. Run stage 3 with the default ten-accepted-post limit. Save Serial output,
   response codes and the ten reading events. Repeat the count query: delta must
   equal ten if all requests succeeded without ambiguous transport failures.
   Compare the new rows' IDs and numeric values with WebSocket data, charts and
   history. Compare at least the last Serial JSON payload across every stage.
   Display formatting may round temperature/SpO₂; stored data must match payload.
7. Verify cards, all three charts, and newest-first history update without reload.
   After submissions stop, wait >10 seconds: browser remains Connected and data
   becomes Stale. Reset/resume; the next accepted measurement should restore Fresh.
8. Verify another patient's detail data is not changed. Do not force abnormal human
   measurements for alerts; existing software tests cover demo alert behavior.
9. Stop ESP32 submissions before a separate three-reading simulator regression.

## Physical evidence record — pending

| Check | Actual result |
| --- | --- |
| Cross-compilation | Passed; HTTP-enabled code, placeholder secrets only |
| ESP32 board / USB port | Not identified; no ESP32 USB serial port visible |
| MAX30102 breakout / supply / pull-ups | Not provided; must inspect markings/docs |
| DS18B20 module/probe / DATA pull-up | Not provided; must inspect actual hardware |
| Upload / detection / Serial values | Not performed |
| ESP32 Wi-Fi / LAN HTTP 201 | Not performed |
| Baseline count / final count / new IDs | Not measured physically |
| Ten ESP32 posts / rows / events / history rows | Not verified |
| Final Serial → payload → SQLite → UI consistency | Not verified |
| Physical stop/resume freshness | Not verified |

Replace pending entries with measured evidence; only then may TASK-021 be marked
complete. Never fill them using synthetic simulator results.

## Troubleshooting and limitations

- MAX30102 missing: check GPIO 21/22, actual module power/GND, address 0x57 and
  library compatibility; use an I²C scanner separately if necessary. Do not guess
  supply voltage. Confirm the physical sensor model even when the driver detects it.
- DS18B20 missing: check GPIO 4, actual pinout/power/GND, required DATA pull-up,
  One-Wire address and family. Use external power. Invalid temperatures are not sent.
- Unusable optical results: check finger placement, motion, ambient light and
  contact. Algorithm validity does not establish medical accuracy. No clamping.
- Connection refused: check Uvicorn, LAN binding, correct host/port, routability
  and narrow firewall permission. 404: verify patient ID and endpoint. 422: compare
  printed JSON with [the API contract](../../docs/ESP32_API_CONTRACT.md).
- HTTP stopped: correct the cause and reset. No automatic infinite retry loop.
- DS18B20 skin/air readings are prototype temperature measurements, not validated
  clinical core body temperature. Do not manipulate a person to force alert values.

Hardware integration demonstrates the IoT pipeline. The sensors and measurements
have not been clinically validated against calibrated medical equipment. Firmware
contains no diagnosis, medical alert rules, MQTT, device authentication or TLS
provisioning. The endpoint remains unauthenticated: trusted demo LAN only.
Production device authentication, HTTPS and credential provisioning remain future
work. Keep the simulator unchanged as the software test/fallback client.
