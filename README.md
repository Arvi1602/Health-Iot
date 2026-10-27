# HealthGuard IoT

Edge-Enabled IoT Healthcare System for Real-Time Patient Monitoring — a college project that gives doctors a live dashboard for heart rate, SpO2, temperature, alerts, and recent patient history.

For the presentation, start with the [software demo runbook](#end-to-end-demo)
and [presentation flow](#presentation-flow-68-minutes). Physical ESP32 verification
is deferred; the demonstrated measurements are software samples.

## Local Backend Setup
The backend now includes the health endpoint, SQLite schema, demo seed data, and
doctor login/logout, validated sensor reading ingestion, authenticated patient
WebSocket streams, and a protected patient monitoring dashboard with live vital
cards and three live Chart.js charts. Configured demo rules now generate stored alerts with an authenticated retrieval API;
the dashboard displays stored demo alerts. Alert WebSocket events are not implemented.

Use Python 3.10 or newer. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Generate a session secret, paste it into `SECRET_KEY` in your local `.env`, then seed
and start the app. Keep `.env` private; it is ignored by Git. Do not overwrite an
existing `.env` when repeating setup.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "from app.database import init_db; init_db()"
python -m app.seed
python -m uvicorn app.main:app --reload
```

Settings load from the project-root `.env`; existing environment variables take precedence.
`SECRET_KEY` signs login sessions. Startup rejects missing, short, or example secrets.
Sessions contain only the doctor ID and expire after eight hours. Cookies are
HttpOnly and SameSite=Strict; `APP_ENV=production` also requires HTTPS cookies.
Local development uses HTTP at `127.0.0.1:8000`.

`DATABASE_URL` defaults to `sqlite:///./healthguard.db`, relative to the working
directory. Run commands from the project root. The initialization command creates
the `doctors`, `patients`, `readings`, and `alerts` tables without inserting data;
it is safe to repeat but does not migrate existing schemas. Database files are ignored by Git.

Each patient belongs to a doctor and has readings and alerts. An alert can optionally
reference a reading. SQLite foreign keys are enforced. Timestamp defaults use UTC
(stored without timezone information in SQLite). `get_db()` provides a session and
closes it after use; future callers must commit successful writes. Tests use temporary
SQLite databases, leaving the local database untouched.

In another terminal, check the running server:

```bash
curl http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok","service":"healthguard-iot"}` (HTTP 200).

Run tests with the virtual environment activated:

```bash
python -m pytest -v
```

## Seed Development Demo Data

From the project root, initialize the database and seed one demo doctor and four
patients with:

```bash
.venv/bin/python -m app.seed
```

This uses the configured `DATABASE_URL` and creates missing tables automatically.
The doctor is Dr. Ananya Sharma (`doctor@healthguard.local`). The patients are Rahul
Kumar, Priya Singh, Arjun Patel, and Meera Joshi; all belong to that doctor.

You can run the command repeatedly. It matches the doctor by email and patients by
name under that doctor and adds only missing records. It also upgrades the exact
TASK-003 placeholder hash for the demo email to an Argon2 hash. Existing real hashes
and other doctors are left untouched. It does not seed readings or alerts. A failed seed
transaction is rolled back, and the database session is always closed.

### Development Login

**LOCAL DEVELOPMENT / COLLEGE DEMO CREDENTIALS ONLY**

Demo Doctor  
Email: `doctor@healthguard.local`  
Password: `HealthGuard123!`

1. Seed the database with `.venv/bin/python -m app.seed`.
2. Start FastAPI with `.venv/bin/python -m uvicorn app.main:app --reload`.
3. Open `http://127.0.0.1:8000/login` and sign in.
4. Open the protected `/dashboard` and select an assigned patient.
5. Click Logout to return to `/login`; `/dashboard` then requires login again.

Only the generated Argon2 hash is stored in SQLite. The seed command never resets an
existing real password. The dashboard displays assigned patients and their latest
readings and live charts; stored demo alerts appear in the dashboard panel.

## Sensor Reading API

`POST /api/readings` with `Content-Type: application/json` accepts and saves a
reading for an existing patient:

```json
{
  "patient_id": 1,
  "heart_rate": 78,
  "spo2": 98,
  "temperature_c": 36.8,
  "recorded_at": "2026-10-06T03:00:00Z"
}
```

Use an actual patient ID from your seeded database; `1` is only an example.
`patient_id` must be a positive SQLite integer, `heart_rate` an integer from 1 to
300, `spo2` a number from 0 to 100, and `temperature_c` a number from 20 to 50.
Numeric strings and booleans are rejected. These are broad input-validation
limits, not clinical or alert thresholds. Unknown fields are rejected; use
`recorded_at` for the timestamp.

`recorded_at` is optional; omission or null uses the existing database UTC default.
Supplied ISO 8601 timestamps are normalized to UTC; timestamps without an offset
are interpreted as UTC. SQLite stores UTC without timezone information, and API
responses include `Z` to identify UTC.

Success returns HTTP 201 with `id`, `patient_id`, the three vital values, and
`recorded_at`. Unknown patients return 404; invalid input returns 422. Database
failures return a generic 500 and roll back the transaction. No patient is created
from sensor input.

This endpoint currently accepts local simulator/device data for the academic
prototype without doctor login. Device authentication is planned for later
hardening and is not part of TASK-005. Persisted readings update the selected
patient’s dashboard cards through the authenticated WebSocket stream.

## Sensor Simulator

The simulator is a separate command-line process that sends JSON over HTTP to the
same `/api/readings` endpoint intended for later ESP32 integration. It does not
write directly to SQLite or run inside FastAPI. ESP32 firmware is prepared;
physical hardware integration is still pending verification.

Seed first, then list the demo patients to find the actual ID to use:

```bash
.venv/bin/python -m app.seed
.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Doctor, Patient
from app.seed import DEMO_DOCTOR_EMAIL
with SessionLocal() as db:
    patients = db.scalars(select(Patient).join(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL)).all()
    for patient in patients:
        print(patient.id, patient.name)
PY
.venv/bin/python -m uvicorn app.main:app --reload
```

In a second terminal at the project root, run continuously or send five readings.
Replace `1` with the patient ID you looked up:

```bash
.venv/bin/python -m app.simulator --patient-id 1
.venv/bin/python -m app.simulator --patient-id 1 --count 5 --interval 0.5 --seed 42
```

`--patient-id` is required. The default interval is 2 seconds; `--interval` accepts
0.1–86400 seconds to avoid a rapid request loop. `--count` must be a positive
integer; omit it to run until Ctrl+C. `--seed` controls randomness for reproducible
values and is unrelated to database seeding. Override the full endpoint using
`--api-url http://127.0.0.1:8000/api/readings` (no URL credentials, query, or fragment).

Each successful request prints HTTP 201 and the values sent. Requests have a
five-second network timeout. HTTP errors or connection failures stop the simulator
with exit code 1; no retries are attempted. Ctrl+C stops cleanly. A timeout can
occur after the server saved a reading, so check SQLite before repeating that run.

Values change gradually within HR 60–100 bpm, SpO2 95–100%, and temperature
36.0–37.5°C. The payload contains only `patient_id`, `heart_rate`, `spo2`, and
`temperature_c`; the server assigns timestamps.

The simulator generates synthetic values for development and demonstration only.
It is not a medical device and the generated values are not clinical data. These
simulation ranges are not diagnostic rules or alert thresholds.

## Real-Time WebSocket Stream

Connect to `/ws/patients/{patient_id}` after logging in as a doctor. The browser
sends the existing signed session cookie; the server checks that the doctor exists
and owns the patient before accepting. Unauthenticated, nonexistent-patient, and
other-doctor requests are rejected with policy code 1008 (a pre-accept rejection
appears as HTTP 403 to network clients). Browser Origin must match the app's origin.

The connection first receives `{"type":"connected","patient_id":1}`. Each newly
committed reading then sends this JSON to all connected viewers of that patient:

```json
{
  "type": "reading",
  "data": {
    "id": 15,
    "patient_id": 1,
    "heart_rate": 78,
    "spo2": 98.0,
    "temperature_c": 36.8,
    "recorded_at": "2026-10-06T06:30:00Z"
  }
}
```

The reading data matches the REST response. Validation or commit failures produce
no event. The existing read-back of database defaults remains inside the transaction;
broadcast happens only after commit. A disconnected or slow viewer is removed and
cannot undo a saved reading or prevent delivery to other viewers. Database sessions
used for handshake authorization close before the stream waits for events.

The simulator still sends HTTP POST requests; it never connects to WebSockets.
For a quick browser-console check on the logged-in app, substitute your patient ID:

```javascript
const stream = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/patients/1`);
stream.onmessage = event => console.log(JSON.parse(event.data));
// When finished:
// stream.close();
```

Use one Uvicorn worker for this local demo: subscriptions live in process memory.
Only new events are streamed; reconnects do not replay missed readings. Authorization
is checked at connection time; existing streams are not revoked by a later cookie
logout. The dashboard closes its own stream on logout or page departure, but this
is not server-side session revocation. Recent reading history is available below; full history pagination and live alert WebSocket delivery are not implemented.

## Doctor Monitoring Dashboard

Seed and start FastAPI as described above, sign in at `/login` with the local demo
credentials, then open `/dashboard`. Only patients assigned to the signed-in doctor
are listed. Select a patient in the sidebar; their database ID appears below their
name. The first patient is selected initially.

The three cards display the latest saved heart rate (bpm), SpO₂ (%), and temperature
(°C). No readings means empty cards, not fabricated measurements. Latest readings
are ordered by `recorded_at`, then ID to resolve ties. Timestamps display in the
browser’s local time. Delayed older events do not replace newer measurements.

In another terminal, use the selected patient's actual ID in place of `1`:

```bash
.venv/bin/python -m app.simulator --patient-id 1 --count 10 --interval 1 --seed 42
```

Simulator → HTTP ingestion → SQLite commit → WebSocket → three live cards.
No page refresh is needed. Values are synthetic and for academic demonstration
only; the dashboard does not classify readings or provide medical advice.

“Connected” describes the browser WebSocket, **not sensor freshness**. Check “Last
updated” for the actual measurement time. If the connection drops, saved values
remain visible. The browser makes at most five reconnection attempts per patient
selection with delays of 1, 2, 4, 8, and 15 seconds. After retries are exhausted,
reload or sign in again. Switching patients closes the old stream and cancels retries.

After subscription, including reconnection, the dashboard re-synchronizes using
`GET /api/patients/{patient_id}/readings/recent`. This endpoint requires the doctor
session and server-side ownership, returns up to 20 readings (or an empty list),
and uses `Cache-Control: no-store`. It initializes and recovers the charts and
cards without periodic polling. The previous single latest-reading endpoint
remains available. Selecting another doctor's patient returns 404.

Logout remains a POST. Client-side cleanup closes this dashboard's socket, but
previously opened streams in other clients are not revoked server-side by logout.
Use the application as a local demonstration with one Uvicorn worker.

### Dashboard browser checks

`tests/dashboard_browser.cjs` uses Playwright and local Google Chrome on macOS.
Install Playwright in a temporary tooling folder (not a production dependency):

```bash
npm install --prefix /private/tmp/healthguard-browser-check playwright
NODE_PATH=/private/tmp/healthguard-browser-check/node_modules node tests/dashboard_browser.cjs
```

The default check starts a temporary server and SQLite database, then tests login,
patient selection, live values, malformed/stale events, isolation, reconnection,
responsive layout, console errors, and logout. It leaves the development database
untouched. Screenshots are written to `/private/tmp/healthguard-dashboard-*.png`.
With the seeded local server already running, `--demo` runs ten simulator readings
against the development database and verifies matching persisted rows and browser
events, plus three readings for Priya to verify patient isolation. This mode
intentionally adds thirteen demo readings and does not delete existing data.

## Live Vital Charts

Below the vital cards, three Chart.js line charts show Heart Rate (bpm), Blood
Oxygen / SpO₂ (%), and Body Temperature (°C). Chart.js 4.5.1 is served locally from
`app/static/vendor/chart.umd.min.js`, downloaded from the pinned npm distribution
`https://registry.npmjs.org/chart.js/-/chart.js-4.5.1.tgz`; its MIT license is retained
alongside it. There is no CDN requirement or additional date/charting library.

On selection, the browser clears the previous patient's series, subscribes to the
existing WebSocket, and loads the selected patient's latest 20 persisted readings.
The fixed-size, authenticated `/api/patients/{patient_id}/readings/recent` endpoint
checks patient ownership. It has no pagination, date filters, or export support.

Readings are ordered oldest to newest by measurement timestamp, then reading ID.
All charts use the same rolling window of at most 20 readings. Each accepted live
event updates the charts, while the cards retain the chronologically latest value.
Duplicate IDs are merged; delayed readings are sorted and trimmed to the window.
Reconnection refreshes recent SQLite data and merges it with live events, recovering
missed points without duplicates or discarding events received during the refresh.

The horizontal axis uses `recorded_at`, with proportional time spacing and local
time labels; tooltips include the local date and time. Measurements sharing a
timestamp may overlap horizontally. No points are fabricated for empty patients.
Charts reuse three instances and are destroyed when leaving the dashboard. They
stack on narrow screens and keep the numeric cards, connection status, and last
measurement time visible.

Run the simulator command in the dashboard section to see the cards and all three
charts update without a refresh. Simulator values are synthetic academic demo
data, not clinical measurements. There are no clinical threshold lines, danger
zones, diagnostic classifications, or alerts.

Browser checks also verify persisted chart initialization, all three live datasets,
a 25-reading rolling-window exercise, patient isolation, duplicate delivery,
reconnect recovery, and desktop/tablet/mobile sizing. The `--demo` check sends ten
real simulator readings and verifies every reading updates each chart consistently.

## End-to-End Demo

This runbook demonstrates **ESP32-contract software sample readings**. The
simulator is the current source; no hardware detection, physical sensor readings,
ESP32 Wi-Fi or upload is claimed. TASK-021 physical verification remains deferred.
Run commands from the project root. Complete [local setup](#local-backend-setup)
once, keep the existing `.env` private, and avoid displaying it during presentation.

### Prepare and start

In terminal A, seed the configured database and start one server worker:

```bash
.venv/bin/python -m app.seed
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Seeding is repeatable; it does not clear old readings/alerts or reset an existing
doctor password. If port 8000 already serves this app, reuse that server rather
than starting a second one. Local software testing does not require LAN binding.

In terminal B, verify health and list actual patient IDs for the demo doctor:

```bash
curl --fail-with-body -i http://127.0.0.1:8000/health
.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Doctor, Patient

with SessionLocal() as db:
    patients = db.scalars(
        select(Patient).join(Doctor)
        .where(Doctor.email == 'doctor@healthguard.local')
        .order_by(Patient.id)
    ).all()
    for patient in patients:
        print(f'{patient.id}: {patient.name}')
PY
```

Expect `/health` HTTP 200. Do not assume patient ID 1. Open
`http://127.0.0.1:8000/login`, use the [development login](#development-login),
select the patient from the overview, and wait for **Connected**. In terminal B,
enter that patient's verified ID (this variable is reused below):

```bash
printf 'Verified patient ID: '
read -r DEMO_PATIENT_ID
```

Run only one sample client at a time for that patient. Existing history and demo
alerts are expected on a reused database; do not delete records for the demo.

### Run ten samples and demonstrate freshness

```bash
.venv/bin/python -m app.simulator \
  --patient-id "$DEMO_PATIENT_ID" --count 10 --interval 1 --seed 42
```

Expect ten HTTP 201 lines. Without refreshing, watch the selected overview,
three vital cards, measurement timestamp, charts and Recent Readings update.
Charts display oldest to newest; history displays newest first. Each is capped
at 20, so ten additions need not increase the displayed row count by ten.

After the simulator exits, leave FastAPI and the dashboard running. Wait more
than ten seconds after the last measurement: **Connected + Stale data** is
expected. Resume with one sample:

```bash
.venv/bin/python -m app.simulator \
  --patient-id "$DEMO_PATIENT_ID" --count 1 --interval 1 --seed 42
```

Expect **Connected + Fresh data** without a page reload. Explain that connection
describes the browser/server WebSocket, while freshness uses `recorded_at`.
The ten-second threshold is software data age, not a clinical threshold.

### Show a stored demo alert

Send this synthetic request only after the simulator stops:

```bash
curl --fail-with-body -i \
  -X POST http://127.0.0.1:8000/api/readings \
  -H 'Content-Type: application/json' \
  -d "{\"patient_id\":${DEMO_PATIENT_ID},\"heart_rate\":110,\"spo2\":90,\"temperature_c\":39.0}"
```

Expect HTTP 201. With the default demo rule configuration this creates one
Reading and three stored alerts: `heart_rate_high`, `spo2_low`, and
`temperature_high`. Custom configured thresholds can change that result; review
[demo alert rules](#demo-alert-rules) before presenting. The browser receives
one **reading** event and refreshes the alert API; there are no alert WebSocket
events. The alert panel shows at most ten recent records, so an already-full
panel keeps the same visible count. These are academic rules, not diagnoses.
Never manipulate a person's measurements to create alerts.

Run the one-sample command again to show that later in-range values update the
cards without deleting historical alerts. A custom rule configuration may also
alert on this sample; no frontend threshold evaluation occurs.

### Finish the walkthrough

Switch to another assigned patient and back: the header, cards, charts, alerts
and history must agree with the selection. Unselected overview cards are
snapshots, not separate live subscriptions. If an assigned patient has no stored
readings, show the no-data state; do not imply the absence of alerts means health.
Click Logout and confirm `/dashboard` returns to login. Stop the local server
with Ctrl+C when the demo is finished. Stored software samples remain in SQLite.

### Presentation flow (6–8 minutes)

| Time | Show | Explain |
| --- | --- | --- |
| 0–1 min | Login and patient overview | The authenticated doctor sees assigned patients; current data is synthetic. |
| 1–3 min | Ten samples updating cards/charts/history | Simulator → HTTP JSON → validation → atomic Reading/Alert persistence → reading WebSocket → dashboard. |
| 3–4 min | Connected/Fresh → Connected/Stale → Fresh | Transport connectivity and measurement age are independent. |
| 4–5 min | Synthetic threshold-crossing request and Demo Alerts | One centralized backend evaluator creates stored academic alerts; browser fetches them. |
| 5–6 min | Patient switching, history and logout | Ownership is enforced server-side; historical measurements remain stored. |
| 6–8 min | Architecture and limitations | Future ESP32 uses the same API; hardware integration is prepared but physically unverified. |

Opening: “HealthGuard demonstrates a live IoT monitoring pipeline using software
sample readings.” Closing: “The software pipeline is verified; real ESP32 and
sensor verification is deferred. This prototype is not clinically validated.”

Useful viva points: SQLite is the persisted source of truth; failed writes do
not broadcast; chart/history IDs prevent duplicate display; reconnect recovers
stored readings; sanity-validation bounds and configurable demo alert rules
serve different purposes. This implementation does not prove on-device analytics.

### Demo recovery and limits

| Symptom | Check/action |
| --- | --- |
| API unreachable | Confirm terminal A is running and `/health` returns 200; check port 8000. |
| Login fails | Confirm seeding and the correct local demo password; seeding does not reset an existing password. |
| POST returns 404 | Recheck the endpoint and the actual patient ID. |
| POST returns 422 | Compare field names, numeric types and values with the API contract; keep validation intact. |
| Connected but Stale | Resume the sample client; connection alone does not imply new measurements. |
| Charts do not change | Confirm the selected patient matches the submitted ID and inspect connection status. |
| Server restarts | Wait for reconnect and recovery; previously persisted values remain available. |

Use a trusted local demo environment: ingestion has no device authentication.
WebSocket subscriptions require a single server worker, and logout in another
client does not revoke an already-open stream. No clinical accuracy, diagnosis,
or treatment advice is claimed. Do not label software samples as physical ESP32
readings. See the [physical verification status](#physical-esp32-demo).

### Repeatable verification

The browser script uses Playwright with the installed macOS Google Chrome at
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`. If the temporary
Playwright installation is missing, restore it without changing application
dependencies:

```bash
npm install --prefix /private/tmp/healthguard-browser-check playwright
```

```bash
.venv/bin/python -m pytest -v
NODE_PATH=/private/tmp/healthguard-browser-check/node_modules node tests/dashboard_browser.cjs
# With the seeded local server running:
NODE_PATH=/private/tmp/healthguard-browser-check/node_modules node tests/dashboard_browser.cjs --demo
```

Both browser modes run an actual simulator subprocess for ten readings at 0.5-second
intervals. A localhost-only test recorder (`tests/recording_proxy.cjs`) forwards
unaltered POST bodies to the real ingestion API and captures its actual responses.
It does not generate responses, inject readings, or replace application layers.
The harness compares simulator output/payloads, REST responses, SQLite rows,
WebSocket events, every card update, and all three chart datasets. It records the
baseline reading count and latest insertion ID before the main run.

Three further simulator readings for Priya must leave Rahul's stream, cards, and
charts unchanged. Invalid readings (422) and unknown patients (404) must add no
rows, events, or UI updates. The isolated mode also checks real reconnect recovery,
rolling limits, and delayed snapshots; its separate malformed-event regression
checks are not used as evidence for the primary simulator flow. Existing Python
tests inject database failures only in temporary databases to verify rollback and
no broadcast. Desktop/tablet/mobile screenshots are saved under `/private/tmp`.

Known limitations remain: logout does not revoke already-open WebSockets in
separate clients; subscriptions require a single application worker; Starlette's
TestClient currently emits a non-blocking httpx deprecation warning.

Latest recorded software QA (TASK-024, 2026-10-11): 247 Python tests passed; the
isolated real-Chrome suite passed login failure, invalid packets, no-data states,
reconnect recovery, demo alerts and responsive checks, with zero uncaught
JavaScript errors. TASK-025 verified the runbook command syntax and JSON against
the schema/default rules; it did not repeat the full suite. These results do not
constitute physical hardware verification.

## Responsive Dashboard

Verified in Chrome at 100% zoom: **1280×720, 1366×768, 1440×900,
1536×864, and 1920×1080**, plus 2560×1440. The existing centered layout uses
responsive grid/flex behavior and vertical scrolling; the recent-reading table
keeps any horizontal scrolling inside its own wrapper. Tablet (820×1000) and
mobile (390×844) regression checks also pass.

Run the shared authenticated browser suite:

```bash
NODE_PATH=/private/tmp/healthguard-browser-check/node_modules node tests/dashboard_browser.cjs
```

It includes `tests/dashboard_responsive.cjs` using the same real login, isolated
database, and server fixture. The viewport checks cover section visibility,
overflow/overlap, chart resizing, keyboard selection, long text, and live readings
and alerts. State and freshness checks also run at 1280×720. Screenshots for
visual review are saved as `/private/tmp/task019-<width>x<height>.png` and
corresponding `-long-text.png` files. These are verified sizes, not a claim of
support for every possible display.

## Connection and Data Freshness

Connection status describes the browser's WebSocket connection to HealthGuard.
Data freshness describes the age of the selected patient's latest measurement,
using its actual `recorded_at`. A connected WebSocket does not guarantee that the
sensor is actively sending readings.

The UI uses `DATA_FRESHNESS_MS = 10_000`: age at or below ten seconds is **Fresh
data**; older readings are **Stale data**. Patients without readings show **No data
yet**; malformed timestamps safely show **Unknown**. Future timestamp ages are
clamped to zero without changing the measurement timestamp.

One local one-second timer updates freshness without network requests. Patient
selection, recovered readings, live readings, and returning to a visible tab
recalculate it immediately. Leaving the dashboard stops the timer. Last known
measurements remain visible if the connection fails. Clock differences between
the sensor/server and browser can affect the displayed age.

Freshness is a software data-age indicator, not a clinical threshold. Becoming
stale does not create stored demo alerts or classify patient health.

## Demo Alert Rules

**DEMO THRESHOLDS ONLY — NOT MEDICAL ADVICE — NOT VALIDATED FOR CLINICAL USE.**

HealthGuard contains configurable academic demonstration rules for evaluating
valid vital readings. These thresholds demonstrate software behavior only. They
are not clinically validated and must not be used for real medical decision-making.

Set these optional values in the existing project `.env` or process environment:

```env
ALERT_HEART_RATE_LOW=60
ALERT_HEART_RATE_HIGH=100
ALERT_SPO2_LOW=95
ALERT_TEMPERATURE_LOW=35.0
ALERT_TEMPERATURE_HIGH=38.0
```

These are the defaults, defined once in `AlertThresholds` in `app/config.py`.
The existing dotenv loader applies; environment variables take precedence.
Restart the application after changing settings. Heart-rate boundaries require
integers in 1–300; SpO₂ requires a finite number in 0–100; temperature boundaries
require finite numbers in 20–50. Low must be strictly less than high. Invalid
settings fail clearly at application import/startup rather than being corrected
silently. These broad validation bounds are separate from demo alert thresholds.

`app.alert_rules.evaluate_reading(reading)` accepts an already-valid `Reading`,
`ReadingCreate`, or `ReadingResponse`. It returns immutable `AlertCandidate`
objects containing `alert_type`, `severity`, and a neutral `message`. Callers can
also pass an explicit validated `AlertThresholds` for independent evaluation.

| Condition | Candidate type |
| --- | --- |
| Heart rate strictly below configured low | `heart_rate_low` |
| Heart rate strictly above configured high | `heart_rate_high` |
| SpO₂ strictly below configured low | `spo2_low` |
| Temperature strictly below configured low | `temperature_low` |
| Temperature strictly above configured high | `temperature_high` |

Values exactly equal to a configured boundary produce no candidate for that rule.
All candidates use the demo severity `warning` and wording such as “Heart rate is
above the configured demo threshold.” There is no diagnosis or clinical risk score.
Multiple matches are returned in deterministic order: heart rate, SpO₂, temperature.
An in-range reading returns an empty list.

Evaluation only reads the supplied values. It does not change the input, open a
database session, create Alert rows, or broadcast events. The ingestion endpoint
now calls this evaluator and persists its candidates separately. The dashboard displays stored alerts; there are no chart threshold lines.
Existing sensor validation still rejects invalid data with HTTP 422; it is not
replaced by these rules. The simulator and visible monitoring behavior are unchanged.

## Stored Demo Alerts

Incoming valid readings are evaluated against the centralized academic demo rules.
Each candidate creates one Alert linked to the originating Reading and Patient.
Reading and alerts commit together; a persistence failure rolls back both and
sends no reading event. In-range readings create no alerts. Invalid sensor data
and unknown patients create neither readings nor alerts.

```http
GET /api/patients/{patient_id}/alerts
```

Doctor authentication is required (unauthenticated requests redirect to `/login`).
Ownership is checked server-side; missing or another doctor's patients return 404.
The API returns the latest **50 stored alerts**, ordered by `created_at DESC, id DESC`,
or `[]` with HTTP 200 when the patient has none. Responses are marked `no-store`.
There is no pagination or configurable limit.

Example response (identifiers are illustrative):

```json
[
  {
    "id": 3,
    "patient_id": 1,
    "reading_id": 54,
    "alert_type": "spo2_low",
    "message": "SpO₂ is below the configured demo threshold.",
    "severity": "warning",
    "is_resolved": false,
    "created_at": "2026-10-06T12:00:00Z"
  }
]
```

Generated alerts start unresolved. Retrieval reads stored rows without re-evaluating
readings. Configuration changes apply to new readings after restart; existing
readings are not backfilled. Repeated threshold-crossing readings each generate
their own alerts. There is no resolution workflow, sound, or alert
WebSocket event; the existing reading response and reading stream are unchanged.

**These alert rules are not clinically validated and must not be used for real
medical decision-making. They demonstrate academic software behavior only.**

## Patient Overview

The existing patient selector is now a single overview/navigation area. It lists
only the logged-in doctor's assigned patients in database-ID order, with name,
age/gender, latest persisted vitals and local measurement time. Patients without
readings show “No readings yet”, never fabricated zero measurements. The selected
card says **Monitoring**; use any other card's **Monitor Patient** action (mouse or
keyboard) to reuse the existing detailed monitoring flow.

**Recent demo alerts (up to 10)** counts the same stored-record subset shown in the
Demo Alerts panel, including both open and resolved records. It is not the total
number of historical alerts or a clinical risk score. Initial counts come from
SQLite; selected-patient counts reuse the existing successful alert refresh.

Selected-patient vitals update from the same reading as the main cards, including
measurement time. Unselected cards are saved snapshots, refreshed when selected.
There is still only one selected-patient WebSocket and no all-patient polling.
The overview is an academic monitoring interface. Displayed values and demo alerts
are not medical diagnoses.

## Dashboard Demo Alerts

Select a patient on the dashboard to view their stored **Demo Alerts** beneath the
charts. The panel uses the authenticated patient alert API and shows the latest
10 records, newest first. The count is the number displayed, not the total in SQLite.
Each item shows its message, textual severity, local `created_at` time, and read-only
Open/Resolved status.

The backend produces these records using the centralized rules. The panel refreshes
on patient selection, accepted reading WebSocket events, and reconnect recovery.
There is no periodic alert polling or separate alert WebSocket event. Switching
patients immediately clears old items; canceled or stale requests cannot replace
the selected patient's panel. Loading, empty, and retrieval-error messages are
shown without interrupting cards or charts.

Alerts are historical stored records: a later in-range reading does not remove or
resolve earlier alerts. No alerts does **not** mean the patient is medically healthy.
**Academic demo alerts only — not clinically validated, not clinical guidance.**
No frontend threshold evaluation, treatment recommendations, sounds, or resolution
controls are provided.

To demonstrate, select a verified patient ID and POST a valid threshold-crossing
reading through the existing ingestion API. With default demo settings, heart rate
110, SpO₂ 90, and temperature 39.0 create three stored demo alerts. One reading
WebSocket event updates the cards/charts and triggers an alert API refresh; the
three records then appear without reloading the page. These values test software
behavior only.

## Recent Reading History

```http
GET /api/patients/{patient_id}/readings?limit=20
```

This endpoint requires doctor login and server-side patient ownership. Unauthenticated
requests redirect to login; missing or unowned patients return 404. Existing patients
without readings return HTTP 200 with `[]`. Results reuse `ReadingResponse`, with UTC
measurement timestamps, ordered by `recorded_at DESC, id DESC`. The default limit is
20; accepted limits are integers from 1 to 100. Invalid limits return 422. Responses
are marked `no-store`.

The dashboard's **Recent Readings** table displays the newest 20 persisted measurements,
with local measurement times, heart rate (bpm), SpO₂ (%) and temperature (°C). Patient
selection clears old rows immediately and loads the selected patient's history.
Reading WebSocket events update the table directly without polling; IDs prevent
duplicates and timestamp ordering handles delayed readings. Initial selection and
reconnect fetch SQLite history again, merging any live readings received during the
fetch. Stale requests cannot replace another patient's table. Loading, empty and
error messages are local to this section. On small screens the table scrolls
horizontally within its container.

The chart-only `/readings/recent` endpoint retains its oldest-first ordering.
There is no pagination, date filtering, export, editing or statistical analysis.
The recent-reading history displays stored sensor measurements. It does not provide
medical diagnosis or treatment advice; simulator measurements are synthetic academic
demo data.

## Dashboard Section States

Demo Alerts and Recent Readings each show one primary state: loading, available
data, an explicit empty message, or a generic retrieval error. Requests clear
visible items while loading; history failures also clear visible rows so errors
do not appear alongside stale data. History keeps its selected-patient merge
buffer internally to preserve live readings arriving during a delayed snapshot.

Alert and history failures are independent. HTTP errors, malformed responses and
connection failures do not close the monitoring WebSocket or interrupt cards and
charts. Selection/reconnect naturally triggers another fetch; no retry queue or
polling was added. Status text uses the same muted presentation in both sections.
Patient-selection status updates use polite announcements; background refreshes
avoid repeated announcements on every sensor event. Empty demo alerts are not a
medical conclusion, and an API error is a software state, not a patient alert.

## ESP32 Integration

The future ESP32 uses the simulator's existing **POST `/api/readings`** endpoint
with **`Content-Type: application/json`**. MAX30102 optical measurements provide
heart rate and SpO₂; DS18B20 provides Celsius temperature. Planned signal wiring:
MAX30102 SDA → GPIO 21, SCL → GPIO 22 (I²C); DS18B20 DATA → GPIO 4 (One-Wire).

See [ESP32 JSON POST contract and tested examples](docs/ESP32_API_CONTRACT.md)
for exact fields/types, validation, optional timestamps, curl and HTTP examples,
201 success, 422 validation errors, 404 unknown patients, and request pseudocode.

The ESP32 must reach the server over the LAN or another routable network and use
the server's actual IP/hostname—not `localhost` or `127.0.0.1`. A server listening
on `0.0.0.0` accepts connections on its interfaces; that bind address is not the
ESP32's request destination. Current HTTP ingestion has **no device authentication**
and is for a trusted academic demo network. Production would require device
authentication, HTTPS and stronger network controls. Firmware preparation and
physical verification instructions are linked below.

## Physical ESP32 Demo

**Current focus (2026-10-11): software sample testing only.** Physical ESP32
verification is deferred at the user's request. Use the existing simulator and
`POST /api/readings` for the demo and regression checks; hardware is not required
for this workflow. Call these **ESP32-contract software sample readings**, not
physical sensor readings. The hardware instructions below are retained for a
future session, and TASK-021 remains incomplete with physical verification
deferred. Software QA proceeds separately at the user's request.

### Software sample verification — 2026-10-10

The **ESP32-contract software sample readings** were verified against the local
API and authenticated dashboard using database-confirmed patient ID 1. One
exact JSON request produced HTTP 201, one Reading row and one reading WebSocket
event. A bounded ten-reading simulator run at one-second intervals produced ten
HTTP 201 responses, ten rows, ten reading events, ten history updates and ten
updates per chart; cards matched the saved values. The history display remained
capped at 20 rows. After an 11.5-second pause, the dashboard remained Connected
and became Stale. One resumed sample restored Fresh without reloading.

This verifies the software API path only. No physical ESP32 upload, sensor
detection, real measurements, Wi-Fi or physical end-to-end result is claimed.
TASK-021 remains incomplete with physical verification deferred.

### Physical verification — deferred

**TASK-021: implementation prepared, physical verification pending.** No real
sensor values, upload, or ESP32-to-dashboard result has been verified yet.

The simulator remains the software test/fallback client; the ESP32 is the intended
physical-demo client. Both use `POST /api/readings`. Do not run them concurrently
for the same patient during physical verification.

See [ESP32 firmware setup and verification](firmware/healthguard_esp32/README.md)
for pinned dependencies, build/upload commands, ignored local secrets, exact
GPIO wiring, staged sensor checks, troubleshooting and an unfilled evidence record.

1. Identify the actual ESP32/MAX30102/DS18B20 modules and verify their power,
   pull-ups and signal wiring before connecting them.
2. Create local `secrets.h`; compile/upload stage 1 for detection, then stage 2
   for actual Serial measurements. Stop if either sensor fails.
3. Stop the simulator. Start FastAPI with LAN binding:

   ```bash
   .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

4. Open the doctor dashboard and select the patient configured in firmware.
5. Configure the server's reachable LAN IP, compile/upload stage 3, and open
   Serial Monitor at 115200 baud. Never share Wi-Fi credentials.
6. Confirm actual sensor values and HTTP 201. Record a database baseline and
   verify ten accepted posts → ten new rows → ten reading events → matching UI.
7. After the firmware's ten-post limit stops submissions, verify Connected + Stale
   after >10 seconds. Reset/resume and verify Fresh without page refresh.

These are pending physical steps, not claimed results. Sensor measurements are
prototype values, not clinically validated measurements. DS18B20 skin/air readings
are not validated clinical core body temperature. Alert rules remain on FastAPI;
no human measurements should be deliberately altered to force demo alerts.

## Version 1 Approach
Version 1 begins with simulated sensor data. Once the complete flow is stable, the simulator can be replaced by an ESP32 using MAX30102 and DS18B20 sensors while keeping the same backend JSON contract.

## MVP Features
- Doctor login
- Patient list/profile
- Live heart rate
- Live SpO2
- Live temperature
- Real-time charts
- Configurable abnormal-reading alerts
- Recent reading history
- Sensor simulator
- ESP32-ready ingestion API

## Planned Stack
- Python
- FastAPI
- SQLite
- SQLAlchemy
- HTML/CSS/JavaScript
- Chart.js
- WebSockets
- Pytest

## Intended Data Flow

```text
Simulator / ESP32
      ↓ HTTP JSON
FastAPI ingestion
      ↓
Validation + alert rules
      ↓
SQLite persistence
      ↓
WebSocket updates
      ↓
Doctor dashboard
```

## Development Rule
Build one vertical slice at a time and test it before starting the next task. See PROJECT.md, RULES.md, and TASKS.md before coding.

## Educational Disclaimer
This is an academic prototype. Demo thresholds and alerts are not a substitute for clinical diagnosis or medical-device validation.

## Fuzzy Logic Monitoring

**ACADEMIC DEMONSTRATION ONLY — NOT CLINICALLY VALIDATED — NOT MEDICAL ADVICE.**
The selected-patient Fuzzy Monitoring Assessment panel is an academic
decision-support demonstration, not diagnosis, clinical risk, triage or treatment
advice. “Normal”, “Warning” and “Critical demo status” are software categories.
A “Normal” result does not establish that a patient is healthy. Check the separate
data-freshness indicator: an assessment can refer to an old stored measurement.

The existing crisp engine (`app/alert_rules.py`) detects explicit configured
boundary crossings and persists demo Alert rows during ingestion. The new pure
`app/fuzzy_logic.py` engine allows overlapping membership, combines all three
vitals and returns a continuous **demo risk score**. It never writes Reading or
Alert rows. Neither system makes a medical diagnosis. The simulator/ESP32 JSON
contract and reading WebSocket messages are unchanged; no fuzzy code runs on
ESP32 or in browser JavaScript.

### Membership configuration and rules

Existing `ALERT_*` settings provide the fuzzy anchors; defaults are HR low/high
60/100 bpm, SpO₂ low 95%, temperature low/high 35/38 °C. Independent positive,
finite transition half-widths in `.env.example` are:

| Setting | Default |
| --- | --- |
| `FUZZY_HEART_RATE_TRANSITION_BPM` | 10 bpm |
| `FUZZY_SPO2_TRANSITION_PERCENT` | 3 percentage points |
| `FUZZY_TEMPERATURE_TRANSITION_C` | 0.5 °C |

These are academic demo settings, not clinically validated. Restart the server
after configuration changes. Low membership is 1 at/below `L-W`, decreases
linearly to 0 at `L+W`, and is 0 above. High membership rises from 0 at `H-W` to
1 at `H+W`. HR and temperature Normal membership is the minimum of the
complements of Low and High; SpO₂ Normal is the complement of Low. Low/high
transition regions must not overlap (`2W <= H-L`); invalid widths or overlapping
regions fail startup rather than being silently adjusted. API input sanity
bounds remain unchanged.

The rule base uses AND = min, OR = max, same-consequent aggregation = max:

- All three Normal → Normal output.
- Any one abnormal vital AND both others Normal → Warning output.
- Any pair of abnormal vitals → Critical output, regardless of the third.

“Abnormal” here means max(Low, High) for HR/temperature and Low for SpO₂; it is
an internal fuzzy term, not a diagnosis. Pair rules cover all low/high
combinations. Output membership curves, centralized in the module, are:

| Output | Shape (vertices) |
| --- | --- |
| Normal | Trapezoid (0, 0, 20, 45) |
| Warning | Triangle (30, 50, 70) |
| Critical | Trapezoid (55, 80, 100, 100) |

Each output curve is clipped at its rule activation, then combined pointwise
using max. Discrete centroid `sum(x * membership) / sum(membership)` over integer
points 0–100 produces the unrounded API score (the panel displays one decimal).
Status uses the largest aggregated rule activation; ties prefer Critical, then
Warning, then Normal. Status is not obtained by applying another score cutoff.
Output bars show **activation degrees**, not probabilities or memberships at
the centroid, and need not sum to 100%. The score is a teaching scale, not a
percentage chance of an outcome. Only the score varies continuously; a discrete
status label can change at a tie.

For default settings, HR 94 / SpO₂ 98 / temperature 36.8 gives HR Normal 0.8 and
High 0.2, both other inputs Normal 1.0, and output Normal 0.8 / Warning 0.2 /
Critical 0.0. The crisp engine creates no alert for this reading, illustrating
partial membership before a hard threshold crossing.

### API and live panel

`GET /api/patients/{patient_id}/fuzzy-assessment` requires the existing doctor
session. Missing or other-doctor patients return 404; unauthenticated access
follows the existing login redirect. Responses use `Cache-Control: no-store`.
The endpoint evaluates the latest persisted Reading by `recorded_at DESC, id
DESC`. Data uses this envelope:

```text
patient_id, reading_id, recorded_at,
assessment: {risk_score, status, input_memberships, output_memberships}
```

An existing patient without readings returns HTTP 200 with `reading_id`,
`recorded_at`, and `assessment` all null. No “Normal” assessment is fabricated.
The API recalculates against current configuration; assessments are not stored
and can change if configuration changes.

The panel renders score, status, local measurement timestamp, output bars and
expandable input bars. It loads on selection, reading events and reconnect,
with cancellation/generation guards against old-patient or out-of-order fetch
responses. Loading, empty and error states remain independent of cards, charts,
alerts and history. There is no extra polling timer or WebSocket message type.

To demonstrate it, use the verified patient ID from the demo runbook:

```bash
.venv/bin/python -m app.simulator \
  --patient-id "$DEMO_PATIENT_ID" --count 5 --interval 1 --seed 42
```

Watch five persisted software readings update cards/charts/history and refresh
the assessment without reloading. Use synthetic JSON for boundary demonstrations;
never attempt to alter a person's measurements to produce a category.
The existing browser suite includes `tests/dashboard_fuzzy.cjs`; run it through
`tests/dashboard_browser.cjs` with the same Playwright setup described above.

### How to explain fuzzy logic in the viva

“Traditional thresholds give a binary crossing result. Fuzzy logic lets a value
near a boundary belong partially to two sets: for example, Heart Rate Normal
0.8 and High 0.2. HealthGuard combines those memberships with SpO₂ and temperature
through IF–THEN rules, then uses centroid defuzzification for a continuous 0–100
demo score. The original crisp alert engine remains separate for stored alerts.
Neither output is clinically validated or a treatment recommendation.”
