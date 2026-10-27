# Development Rules

## General
- Follow PROJECT.md and TASKS.md.
- Keep Version 1 small enough to finish for the college deadline.
- Do not add features outside the approved MVP.
- Do not change the stack unless there is a concrete blocker.
- Prefer the smallest correct implementation.
- Do not modify unrelated files while completing a task.
- Keep code easy to explain in a viva/project presentation.

## Development Order
Use this loop for every task:

READ → UNDERSTAND → PLAN → IMPLEMENT → TEST → REVIEW → FIX → REPORT → UPDATE TASKS

Do not knowingly move to the next task while the current task is broken.

## Architecture
- Keep UI code separate from database code.
- Put database operations in dedicated data/service modules.
- Keep alert thresholds/rules in one configuration/rules module.
- The simulator and ESP32 must use the same ingestion JSON contract.
- Use one FastAPI application for Version 1; do not split into microservices.
- Use WebSockets only for live browser updates; persist readings through normal backend logic.

## Authentication
- Never store plaintext passwords.
- Protect doctor-only pages/routes.
- Do not expose secret keys in source code.
- Keep secrets in environment variables.

## Sensor Data
- Validate patient_id and numeric sensor values server-side.
- Reject malformed packets cleanly.
- Store a server timestamp when necessary.
- Do not claim demo alert thresholds are medical diagnosis.

## UI
- Desktop-first.
- Keep navigation simple.
- Show loading, empty, error, disconnected, and no-data states.
- Always show when the latest reading was received.
- Keep charts readable rather than decorative.

## Testing
- Run relevant tests after every task.
- Test the happy path and at least one failure path.
- Run a production/import check before declaring the backend stable.
- Manually verify the browser flow for live updates.

## Git
- Make small commits after working functionality is verified.
- Suggested commit prefixes: feat, fix, test, docs, chore.
