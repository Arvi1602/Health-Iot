# Tasks

## Current Phase
Phase 5 — Demo QA

## Current Task
None — TASK-FUZZY-001 is complete.
TASK-021 physical verification remains deferred and incomplete.

TASK-025 Prepare README demo steps and presentation flow is complete
(2026-10-11). The existing End-to-End Demo section now provides startup/health
checks, database-confirmed patient selection, ten software samples, freshness
stop/resume, a synthetic demo-alert POST, switching/logout, a 6–8 minute
presentation outline, troubleshooting and prototype limitations. It clearly
separates software evidence from deferred physical ESP32 verification. All six
runbook shell blocks passed bash syntax checks; the patient-query Python parsed;
the rendered curl JSON passed ReadingCreate and produced the three expected
default demo alert candidates. Simulator CLI options matched its actual help.
No production code changed; the full suite was not rerun for documentation-only
changes (TASK-024's 247 tests and browser QA remain the latest recorded runs).
No later task is listed; no new task was invented.

TASK-024 Verify login failure, bad sensor packet, no-data state, reconnect, and
abnormal-reading alert is complete (2026-10-11). Added a real browser failed-login
check in a separate unauthenticated context: HTTP 401, generic error, no session
cookie and dashboard still protected. Invalid packets returned 422 with no
Reading/Alert or broadcast; unknown patients returned 404. Empty patients showed
no-data/empty states without invented values. Reconnect recovered a missed
reading once with no duplicates. A software threshold-crossing reading generated
three stored demo alerts and one reading event; the panel/cards/charts updated,
and later in-range readings retained historical alerts. All 247 Python tests
passed (one existing TestClient deprecation warning). The complete isolated
Chrome suite passed including freshness, logout and responsive regressions,
with zero uncaught JavaScript errors; the intentionally rejected login returned
an expected HTTP 401. JavaScript syntax and application import passed. No
production code changes were needed. TASK-021 physical verification remains
deferred. TASK-025 documentation results are recorded above.

TASK-023 Run manual end-to-end browser QA is complete (2026-10-11).
The existing Playwright suite drove real Chrome against an isolated FastAPI
server and temporary SQLite database; desktop/tablet/mobile screenshots were
also visually inspected. Login/protected routes/logout, patient selection,
overview, cards, charts, alerts, history, loading/empty/error states, isolation,
reconnect and freshness stop/resume passed. Ten software simulator submissions
produced ten HTTP 201 responses, ten Reading rows, ten reading WebSocket events
and 30 chart updates, with matching persisted/UI values. Responsive checks passed
at 1280x720, 1366x768, 1440x900, 1536x864, 1920x1080 and 2560x1440, plus tablet
and mobile, with no page overflow and zero JavaScript console errors.
The missing temporary Playwright dependency was restored outside the repository;
no production code changes were needed. Application import passed. This was
software browser QA, not physical ESP32 verification. TASK-024 results are
recorded above.

TASK-022 Run backend tests is complete (2026-10-11), following the user's
instruction to proceed with software QA while physical verification is deferred.
All 247 tests passed in 8.82 seconds. Coverage includes authentication,
database/seed data, ingestion, simulator, alert rules/persistence/API, reading
history, patient overview, dashboard and WebSockets. `compileall -q app`,
`pip check` and application import also passed. The existing non-blocking
Starlette TestClient deprecation warning remains; no production fixes were
needed. TASK-023 browser QA results are recorded above.

## Deferred TASK-021

**Status: Implementation prepared; software sample verified; physical verification pending.**

Scope update (2026-10-11): physical verification is deferred at the user's
request. Current work focuses on ESP32-contract software sample testing with
the existing simulator and API. Hardware availability is not a prerequisite for
these tests; no USB detection, upload or sensor checks are planned for now.
TASK-021 remains unchecked because its original physical acceptance criteria
have not been verified. The later instruction to start TASK-022 authorizes
software QA to proceed without claiming physical completion.

Software sample verification (2026-10-10): verified local patient ID 1 before
submission. One exact ESP32-contract software sample request returned HTTP 201,
added one Reading and delivered one reading WebSocket event with matching
cards/charts/history and Fresh status. Ten simulator submissions at one-second
intervals returned ten HTTP 201 responses, added ten Readings, delivered ten
reading events and updated history and each of the three charts ten times.
After 11.5 seconds without submissions, connection remained Connected while
freshness became Stale; one resumed software sample restored Fresh. These are
software results only, not ESP32 upload, sensor, Wi-Fi or physical E2E evidence.
The same run passed all 247 Python tests, compileall, pip check and the existing
isolated browser suite (including desktop/tablet/mobile, reconnect and logout)
with zero JavaScript console errors. The LAN-bound server returned HTTP 200 at
`/health`. No production code was changed.

Firmware compilation and software regressions have passed. TASK-021 remains
incomplete because no ESP32 USB serial device has been detected and the actual
sensor modules have not been identified. No further code changes are planned
unless software sample testing reveals a defect. The simulator is the current
demo and test source.

Deferred reference — if physical verification is resumed later:

1. Connect only the ESP32 using a known USB data cable; verify its actual port
   with `pio device list` and `ls /dev/cu.*`.
2. Identify the ESP32/USB-UART chip, MAX30102 breakout and DS18B20 type; verify
   sensor power and pull-up requirements before powering the sensors.
3. Upload the existing stage-1 firmware to the verified board and confirm Serial
   communication at 115200 baud, then wire and verify sensor detection.
4. Verify real measurements, then ESP32-only HTTP 201 submissions, matching
   SQLite rows/WebSocket events/dashboard values, and freshness stop/resume.

Only mark TASK-021 complete after physical evidence is recorded. Physical
verification is deferred independently of the authorized software QA work.

## Phase 1 — Foundation
- [x] TASK-001 Initialize FastAPI project structure and basic app health check.
- [x] TASK-002 Add SQLite + SQLAlchemy models for doctors, patients, readings, and alerts.
- [x] TASK-003 Add seed data for one doctor and a few demo patients.
- [x] TASK-004 Build doctor login/logout and protect dashboard routes.

## Phase 2 — First Complete Monitoring Flow
- [x] TASK-005 Add sensor ingestion endpoint with validated JSON payload.
- [x] TASK-006 Save valid readings to SQLite.
- [x] TASK-007 Build a sensor simulator that sends readings to the ingestion endpoint.
- [x] TASK-008 Add WebSocket connection and broadcast latest patient readings.
- [x] TASK-009 Build patient monitoring UI with live vital cards.
- [x] TASK-010 Add live Chart.js charts for heart rate, SpO2, and temperature.
- [x] TASK-011 Test simulator → API → database → WebSocket → dashboard end-to-end.

## Phase 3 — Alerts and History
- [x] TASK-012 Add centralized configurable demo alert rules.
- [x] TASK-013 Store generated alerts and expose them through the API.
- [x] TASK-014 Build dashboard alert panel.
- [x] TASK-015 Add recent reading history endpoint and table.
- [x] TASK-016 Add alert/history loading, empty, and error states.

## Phase 4 — Polish and Hardware Readiness
- [x] TASK-017 Build patient list/dashboard overview.
- [x] TASK-018 Add connection/data freshness indicator.
- [x] TASK-019 Verify responsive behavior for common desktop sizes.
- [x] TASK-020 Document ESP32 JSON POST contract and example request.
- [ ] TASK-021 Replace simulator with ESP32 only after simulator flow is stable.

## Phase 5 — Demo QA
- [x] TASK-022 Run backend tests.
- [x] TASK-023 Run manual end-to-end browser QA.
- [x] TASK-024 Verify login failure, bad sensor packet, no-data state, reconnect, and abnormal-reading alert.
- [x] TASK-025 Prepare README demo steps and presentation flow.

## TASK-001 Acceptance Criteria
- FastAPI application starts successfully.
- GET /health returns HTTP 200 and a small JSON status response.
- Static/templates folders are prepared for the later dashboard.
- Basic project settings/environment loading exists.
- No database or feature logic is added prematurely.
- A small automated test verifies /health.

## TASK-001 Expected Files
- app/main.py
- app/config.py
- tests/test_health.py
- requirements.txt or pyproject.toml
- .env.example
- .gitignore

## TASK-001 Testing
- Start the FastAPI development server.
- Open /health in the browser or request it with a client.
- Run pytest.

## Known Issues
All 247 TASK-001 through TASK-017 Python regression tests pass, including 41 alert-rule/configuration tests and 27 alert persistence/API integration tests. Isolated and local-demo Chrome dashboard checks also pass. Starlette still emits the existing non-blocking deprecation warning for its TestClient httpx integration.
WebSocket subscriptions are in-memory for a single Uvicorn worker; no missed-event replay is provided. Authorization is checked at connection time, and a later cookie logout does not revoke an already-open stream.

## Next Step
TASK-017 is complete: the existing patient selector is now one responsive overview grid with assigned patients, age/gender, latest persisted vitals/time, explicit no-reading text and Monitoring selection labels. A single database query prepares the owned snapshot with deterministic timestamp/id ordering. Recent demo alert counts are explicitly capped at ten to match the panel, include resolved records, and reuse existing alert fetches. Only the selected patient's overview updates live; other cards remain snapshots until selected. All 247 Python tests (five new overview tests), syntax, compilation, dependency/import, startup and HTTP 200 health checks passed. The full browser suite passed overview/live consistency, rapid switching, single subscription, isolation and TASK-016 state regressions, with zero console errors. A real five-reading simulator run for verified Rahul ID 1 produced five HTTP 201 responses and five SQLite rows, with matching overview/cards/charts/history. Desktop/tablet/mobile were visually reviewed. No patient CRUD, classification, all-patient polling, extra WebSockets or TASK-018 work was introduced.
TASK-018 is complete: selected-patient connection and data freshness are separate indicators. Freshness uses the latest accepted recorded_at, with age <= 10 seconds Fresh and older measurements Stale; no readings show No data yet and malformed timestamps have a safe fallback. One local timer ages data without requests and is cleaned up on departure. Visibility, selection and reconnect recovery recalculate freshness. All 247 Python tests and JavaScript syntax, compilation, dependency/import, startup and HTTP 200 health checks passed. The browser suite verified real simulator stop/resume, exact boundaries, future clock skew, connected/stale and disconnected/fresh states, local aging while disconnected, patient switching, reconnect recovery, stale/invalid event protection, one active timer and logout cleanup. Existing cards/charts/alerts/history/overview and state regressions passed with zero console errors; desktop/tablet/mobile screenshots were reviewed. No backend alert changes or TASK-019 functionality was added.
TASK-019 is complete: the shared authenticated browser suite now verifies 1280×720, 1366×768, 1440×900, 1536×864, 1920×1080 and optional 2560×1440 at normal zoom. Bounds, overlap, horizontal page overflow, chart instance retention, long text, keyboard controls, scrolling, switching and live reading/alert updates passed. Loading/empty/error states and freshness aging were exercised at 1280×720; tablet/mobile regressions passed. All desktop screenshots and representative long-text/state/tablet/mobile captures were visually reviewed. No production UI changes were needed. All 247 Python tests, syntax, compilation, dependencies, import, startup, HTTP 200 health and full browser regression checks passed, with zero JavaScript console errors. No TASK-020 work was implemented.
TASK-020 is complete: README links to docs/ESP32_API_CONTRACT.md, documenting the actual POST schema, strict numeric types, forbidden extra fields, validation bounds, optional timestamp/default/UTC behavior, planned GPIO 21/22 and GPIO 4 sensor connections, LAN addressing, prototype security, response/retry guidance and pseudocode. The obsolete PROJECT.md device_id/timestamp sample now matches the supported contract. A local Uvicorn --reload server with isolated seeded SQLite verified the documented curl request: HTTP 201, one Reading, zero Alerts and one authenticated reading WebSocket event. The timestamped response example matched exactly; UTC/offset/naive/date-only/null/microsecond timestamp cases passed. Seventeen invalid/type/unknown-patient cases returned 422/404 with no rows or events. Three actual simulator requests produced three 201 responses, rows and events. All 247 Python tests, compilation, dependency/import checks and HTTP 200 health passed. No production code, frontend, firmware or TASK-021 functionality changed; physical hardware/LAN verification remains future work.
TASK-021 is in progress: firmware and staged detection/measurement/HTTP instructions are prepared under firmware/healthguard_esp32. Local secrets and build artifacts are ignored. PlatformIO Core 6.2.0 / Espressif32 6.12.0 / esp32dev successfully cross-compiled the final HTTP-enabled placeholder build (47,916 bytes RAM, 819,713 bytes flash), using SparkFun MAX3010x 1.1.2, OneWire 2.3.8 and DallasTemperature 3.11.0. No ESP32 USB serial port was visible and actual MAX30102/DS18B20 module/power details have not been supplied. Physical detection, values, upload, Wi-Fi, ten-post database/WebSocket/dashboard consistency and stop/resume freshness remain unverified. All 247 Python tests and the complete isolated browser/simulator suite passed with zero console errors; LAN-bound FastAPI startup and HTTP 200 health passed. No backend/frontend/simulator changes or TASK-022 feature work were made. Keep TASK-021 unchecked and Current Task unchanged until physical acceptance criteria pass.

## Separate Feature Work
- [x] TASK-FUZZY-001 — Add fuzzy-logic monitoring assessment.

Academic-only pure fuzzy engine, authenticated owned latest-reading API and
selected-patient panel. Existing crisp alerts, ingestion/WebSocket contracts and
TASK-021 physical-verification status remain unchanged.

Verification: 316 Python tests passed (247 existing, 59 fuzzy unit/configuration,
10 fuzzy API); one existing TestClient deprecation warning remains. Compileall,
pip check, application import and JavaScript syntax checks passed. The full
isolated Chrome suite passed with zero console errors, including five simulator
HTTP 201 responses, five reading events and five observed fuzzy refreshes with
matching persisted history/charts. Loading/empty/error states, input/output bars,
patient-switch and same-patient response races, reconnect recovery and independent
API failures passed. Desktop/tablet/mobile fuzzy screenshots were visually
reviewed; a wrapping percentage label was corrected. Existing responsive,
freshness, authentication/logout, overview, alert and history checks passed.
The updated application passed health checks in the isolated test server.
No fuzzy results are persisted and no device/reading WebSocket fields changed.
The optional restart of older localhost servers was rejected by automatic
approval review due to an approval-service usage limit; local server refresh
remains pending, independently of the successful isolated feature verification.
