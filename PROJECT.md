# HealthGuard IoT — Project Definition

## 1. Project Name
HealthGuard IoT — Edge-Enabled IoT Healthcare System for Real-Time Patient Monitoring

## 2. Project Idea
A desktop-first web dashboard for doctors to monitor patient vital signs in real time. Version 1 uses simulated sensor data and is designed so the simulator can later be replaced by an ESP32 with MAX30102 and DS18B20 sensors.

## 3. Problem
Doctors need a simple way to see important patient vital signs continuously instead of checking disconnected readings manually. The project will collect sensor readings, process them, show live values and charts, store history, and raise clear alerts when configured demo thresholds are crossed.

## 4. Target Users
Primary user: doctors.

Main need: quickly understand a patient's current status, notice abnormal readings, and review recent history from one dashboard.

## 5. Main Outcome
A doctor can log in, select a patient, view live heart rate, SpO2, and temperature, see real-time charts, receive abnormal-reading alerts, and review recent historical readings.

## 6. Version 1 MVP
1. Doctor login.
2. Patient list and basic patient profile.
3. Live heart rate display.
4. Live SpO2 display.
5. Live temperature display.
6. Real-time charts for incoming readings.
7. Abnormal-reading alert panel using configurable demo thresholds.
8. Recent reading history stored in a local database.
9. Sensor simulator that produces realistic-looking demo data.
10. A clean ingestion interface so the simulator can later be replaced by ESP32 data.

## 7. Out of Scope for Version 1
- Payments.
- Video consultation.
- Prescription management.
- Full hospital management system.
- AI diagnosis or medical decision-making.
- Patient mobile app.
- Multi-hospital tenancy.
- Production-grade regulatory compliance.

## 8. Project Constraints
- College/academic demonstration project.
- Deadline: this weekend.
- Desktop-first UI.
- Keep the stack simple and easy to explain during a presentation.
- Build and verify one end-to-end feature at a time.

## 9. Assumptions
- Version 1 can use one seeded doctor account for demonstration.
- Version 1 can begin with a small number of seeded patients.
- The simulator will generate heart rate, SpO2, and temperature values.
- Demo thresholds are configurable and are not presented as clinical diagnosis.
- The first database can be SQLite because the goal is a local/college demo.
- ESP32 integration comes only after the simulator-to-dashboard flow is stable.

## 10. Lightweight Research Notes
### Technical choice
FastAPI supports WebSocket endpoints and JSON messaging, making it suitable for pushing live readings from the backend to the dashboard. Chart.js is suitable for lightweight browser-based time-series charts.

### Useful product ideas
- Keep the doctor's current patient and alerts visible without navigating through many pages.
- Use status badges and timestamps so the doctor can see whether data is fresh.
- Separate current vitals from historical trends.

### Things to avoid
- Over-engineering with multiple backend services.
- Building a full hospital information system.
- Adding AI diagnosis to the first version.

## 11. Tech Stack
### Frontend
HTML + CSS + vanilla JavaScript.

Reason: fastest to build, easiest to debug, and easiest to explain for a short college deadline.

### Charts
Chart.js.

Reason: lightweight and well suited to real-time line charts.

### Backend
FastAPI (Python).

Reason: simple API development, WebSocket support, clear Python code, and good fit for later ESP32 ingestion.

### Database
SQLite with SQLAlchemy.

Reason: zero external database setup for the college demo, while keeping a clean data layer.

### Authentication
Simple server-side session/cookie authentication with hashed passwords.

Reason: enough for a college demo without adding an external identity provider.

### Real-Time Transport
WebSocket from FastAPI to browser dashboard.

Reason: live dashboard updates without repeated page refreshes.

### Device/Simulator Ingestion
HTTP POST with JSON to a FastAPI endpoint.

Reason: both the simulator and ESP32 can send the same payload format.

### Testing
Pytest + FastAPI TestClient, plus manual browser checks.

### Deployment
Local demo first. Optional preview deployment only after the local version is stable.

## 12. Simple Architecture

```text
SIMULATOR (first) / ESP32 (later)
          |
          | HTTP POST JSON
          v
      FASTAPI API
          |
          +------> Validation + edge/demo rule checks
          |
          +------> SQLite / SQLAlchemy
          |
          +------> WebSocket broadcast
                         |
                         v
                 DOCTOR DASHBOARD
                  |   |    |    |
               Vitals Charts Alerts History
```

## 13. Sensor JSON Contract

```json
{
  "patient_id": 1,
  "heart_rate": 78,
  "spo2": 98,
  "temperature_c": 36.8,
  "recorded_at": "2026-10-08T14:30:00Z"
}
```

The simulator and future ESP32 use `POST /api/readings`. Replace patient ID 1
with an existing database ID. `recorded_at` is optional; unsupported fields are
rejected. See [ESP32 API Contract](docs/ESP32_API_CONTRACT.md) for exact types,
validation, networking and tested examples. Firmware is prepared under
`firmware/healthguard_esp32`; physical integration verification is pending.

## 14. Main Modules
- Authentication
- Patient management/read-only patient profiles
- Sensor ingestion
- Reading validation
- Alert/rule evaluation
- Reading persistence
- WebSocket live updates
- Dashboard UI
- History API/UI
- Simulator

## 15. Data Model
### doctors
- id
- name
- email
- password_hash

### patients
- id
- name
- age
- sex_or_label (optional for demo)
- room_or_bed (optional)

### readings
- id
- patient_id
- heart_rate
- spo2
- temperature_c
- recorded_at

### alerts
- id
- patient_id
- reading_id
- metric
- message
- severity
- created_at
- acknowledged

## 16. Minimum Screens
### 1. Login
- Email/username
- Password
- Error state

### 2. Dashboard / Patient List
- Patient cards/table
- Latest heart rate, SpO2, temperature
- Current status
- Latest update time
- Alert count

### 3. Patient Monitoring Screen
- Patient summary
- Three large vital cards
- Live line charts
- Alert panel
- Recent readings table
- Connection/data freshness indicator

## 17. Design Direction
- Desktop-first medical dashboard.
- Clean, professional, minimal layout.
- High readability and clear spacing.
- Use consistent cards for vitals.
- Use neutral UI by default and reserve warning/error emphasis for alerts.
- Show loading, empty, disconnected, and error states.

## 18. Alert Rule Principle
Thresholds must live in one configuration file/module rather than being scattered through the UI and API.

For the college demo, threshold rules are educational/demo rules only and must not be described as clinical diagnosis. Exact threshold values should follow the project's approved report/rule matrix.

## 19. Success Criteria
The project is successful when:
1. A doctor can log in.
2. At least one patient can be selected.
3. The simulator sends readings continuously.
4. The dashboard updates live without page refresh.
5. Heart rate, SpO2, and temperature are displayed and charted.
6. Readings are saved and visible in history.
7. A configured abnormal reading creates a visible alert.
8. The app survives refresh/reconnect without becoming unusable.
9. The simulator can later be replaced by an ESP32 sending the same JSON format.

## 20. Version 1 Demo Flow
1. Start backend.
2. Open login page.
3. Log in as doctor.
4. Start simulator.
5. Open a patient.
6. Show live values changing.
7. Show live chart updates.
8. Trigger one abnormal simulated value.
9. Show alert creation.
10. Show historical readings.
11. Explain that the ESP32 will send the same JSON packet in the hardware stage.

## 21. Academic Fuzzy Monitoring Extension

TASK-FUZZY-001 adds a pure backend Mamdani fuzzy evaluator alongside the existing
crisp alert engine. It reuses configured demo thresholds as overlap anchors,
combines partial memberships with min/max rules and exposes an authenticated,
owned latest-reading assessment with a centroid 0–100 demo score. A separate
selected-patient panel renders the score and membership degrees. Assessment is
not persisted; ingestion and reading WebSocket contracts remain unchanged.
Normal/Warning/Critical are academic software categories, not diagnoses,
validated clinical risk or treatment advice. Physical ESP32 verification remains
deferred and incomplete; this feature uses the verified software sample path.
