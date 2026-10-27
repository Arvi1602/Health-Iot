/* Run with Playwright available through NODE_PATH; uses a temporary SQLite DB. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { once } = require('node:events');
const python = path.resolve('.venv/bin/python');
const demo = process.argv.includes('--demo');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'healthguard-dashboard-'));
const env = demo ? process.env : {...process.env, DATABASE_URL: `sqlite:///${temp}/browser.db`, SECRET_KEY: 'isolated-browser-test-secret-at-least-32-characters', APP_ENV: 'test'};
const py = code => execFileSync(python, ['-c', code], {env, encoding: 'utf8'}).trim();
let server, browser, recorder;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function poll(test, label) {
    for (let i = 0; i < 100; i++) { if (await test()) return; await delay(100); }
    throw new Error(`Timed out: ${label}`);
}
(async () => {
    let base = 'http://127.0.0.1:8000';
    if (!demo) {
        py('from app.seed import seed_demo_data; seed_demo_data()');
        py(`from app.database import SessionLocal
from app.models import Doctor, Patient
with SessionLocal() as db:
    doctor = Doctor(name='Other doctor', email='private@example.com', password_hash='unused')
    db.add(doctor)
    db.flush()
    db.add(Patient(id=99, name='Private Other Patient', age=40, gender='Female', doctor_id=doctor.id))
    db.commit()`);
        const portProbe = net.createServer();
        portProbe.listen(0, '127.0.0.1'); await once(portProbe, 'listening');
        const port = portProbe.address().port;
        await new Promise(resolve => portProbe.close(resolve));
        base = `http://127.0.0.1:${port}`;
        server = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--port', String(port)], {env, stdio: 'ignore'});
    }
    await poll(async () => { try { return (await fetch(`${base}/health`)).ok; } catch { return false; } }, 'server startup');
    const patients = JSON.parse(py(`import json
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Patient, Doctor
with SessionLocal() as db:
    rows = db.scalars(select(Patient).join(Doctor).where(Doctor.email == 'doctor@healthguard.local').order_by(Patient.id)).all()
    print(json.dumps([{'id': p.id, 'name': p.name} for p in rows]))`));
    const a = patients.find(p => p.name === 'Rahul Kumar');
    const b = patients.find(p => p.name === 'Priya Singh');
    assert(a && b);
    recorder = await require('./recording_proxy.cjs')(base);
    const seedState = () => JSON.parse(py(`import json
from sqlalchemy import select, func
from app.database import SessionLocal
from app.models import Doctor, Patient
with SessionLocal() as db:
    doctors = db.scalars(select(Doctor).where(Doctor.email == 'doctor@healthguard.local')).all()
    print(json.dumps([len(doctors), db.scalar(select(func.count()).select_from(Patient).where(Patient.doctor_id == doctors[0].id))]))`));
    const seeded = seedState();
    py('from app.seed import seed_demo_data; seed_demo_data()');
    assert.deepEqual(seedState(), seeded);
    assert.deepEqual(seeded, [1, 4]);
    const dbState = patientId => JSON.parse(py(`import json
from sqlalchemy import select, func
from app.database import SessionLocal
from app.models import Reading
with SessionLocal() as db:
    query = select(func.count(Reading.id), func.max(Reading.id))
    if ${patientId === null ? 'False' : 'True'}:
        query = query.where(Reading.patient_id == ${patientId === null ? 'None' : patientId})
    count, latest_id = db.execute(query).one()
    print(json.dumps({'count': count, 'latestId': latest_id}))`));
    const count = () => Number(py(`from sqlalchemy import select, func
from app.database import SessionLocal
from app.models import Reading
with SessionLocal() as db:
    print(db.scalar(select(func.count()).select_from(Reading).where(Reading.patient_id == ${a.id})))`));
    browser = await chromium.launch({headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args: ['--disable-gpu']});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    // Negative login uses its own context so a failed attempt cannot inherit a session.
    const rejectedContext = await browser.newContext();
    try {
        const rejectedPage = await rejectedContext.newPage();
        const scriptErrors = [];
        rejectedPage.on('pageerror', error => scriptErrors.push(error.message));
        await rejectedPage.goto(`${base}/login`);
        await rejectedPage.locator('[name=email]').fill('doctor@healthguard.local');
        await rejectedPage.locator('[name=password]').fill('intentional-invalid-test-password');
        const [failure] = await Promise.all([
            rejectedPage.waitForResponse(response => new URL(response.url()).pathname === '/login' && response.request().method() === 'POST'),
            rejectedPage.getByRole('button', {name: 'Login', exact: true}).click()
        ]);
        assert.equal(failure.status(), 401);
        await rejectedPage.locator('[role=alert]').waitFor();
        assert.equal(await rejectedPage.locator('[role=alert]').textContent(), 'Invalid email or password.');
        assert(!(await rejectedContext.cookies()).some(cookie => cookie.name === 'healthguard_session'));
        await rejectedPage.goto(`${base}/dashboard`);
        assert.equal(new URL(rejectedPage.url()).pathname, '/login');
        assert.deepEqual(scriptErrors, []);
        console.log(JSON.stringify({loginFailure: 'passed', status: 401, sessionCreated: false, dashboard: 'protected', uncaughtErrors: 0}));
    } finally {
        await rejectedContext.close();
    }
    await context.addInitScript(() => {
        window.activeFreshnessTimers = new Set();
        const nativeInterval = window.setInterval, nativeClear = window.clearInterval;
        window.setInterval = (callback, ...args) => {
            const id = nativeInterval(callback, ...args);
            if (callback.name === 'updateFreshnessIndicator') activeFreshnessTimers.add(id);
            return id;
        };
        window.clearInterval = id => { activeFreshnessTimers.delete(id); return nativeClear(id); };
        window.testSockets = [];
        window.testReadingEvents = [];
        const Native = window.WebSocket;
        window.WebSocket = class extends Native {
            constructor(...args) {
                super(...args); window.testSockets.push(this);
                this.addEventListener('message', event => {
                    try { const message = JSON.parse(event.data); if (message.type === 'reading') window.testReadingEvents.push(message.data); } catch {}
                });
            }
        };
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto(`${base}/dashboard`);
    assert.equal(new URL(page.url()).pathname, '/login');
    await page.locator('[name=email]').fill('doctor@healthguard.local');
    await page.locator('[name=password]').fill(py('from app.seed import DEMO_PASSWORD; print(DEMO_PASSWORD)'));
    await page.getByRole('button', {name: 'Login', exact: true}).click();
    await page.waitForURL('**/dashboard');
    await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'connection');
    await poll(async () => !(await page.locator('#reading-state').textContent()).includes('Loading'), 'initial refresh');
    assert.equal(await page.locator('.patient-button').count(), 4);
    assert(!await page.getByText('Private Other Patient').count());
    if (!demo) {
        assert.equal(await page.locator('#heart-rate').textContent(), '—');
        assert.match(await page.locator('#reading-state').textContent(), /No readings available/);
    }
    assert.equal(await page.locator('.chart-container canvas').count(), 3);
    const chartData = () => page.evaluate(() => ['heart_rate', 'spo2', 'temperature_c'].map(key =>
        Chart.getChart(`chart-${key}`).data.datasets[0].data));
    const assertCharts = async patientId => {
        const recent = await (await context.request.get(`${base}/api/patients/${patientId}/readings/recent`)).json();
        await poll(async () => JSON.stringify((await chartData())[0].map(p => p.id)) === JSON.stringify(recent.map(r => r.id)), 'chart IDs');
        const datasets = await chartData();
        ['heart_rate', 'spo2', 'temperature_c'].forEach((key, index) => {
            assert.deepEqual(datasets[index], recent.map(r => ({x: Date.parse(r.recorded_at), y: r[key], id: r.id, patient_id: r.patient_id, recorded_at: r.recorded_at})));
        });
    };
    await assertCharts(a.id);
    await page.evaluate(() => {
        window.chartUpdates = [];
        window.cardUpdates = [];
        new MutationObserver(() => {
            const point = Chart.getChart('chart-heart_rate').data.datasets[0].data.at(-1);
            if (point) cardUpdates.push({id: point.id, heart_rate: Number(document.querySelector('#heart-rate').textContent),
                spo2: Number(document.querySelector('#spo2').textContent), temperature_c: Number(document.querySelector('#temperature').textContent),
                recorded_at: document.querySelector('#last-updated').dateTime});
        }).observe(document.querySelector('.vital-grid'), {childList: true, subtree: true});
        Chart.register({id: 'test-observe-updates', afterUpdate(chart) {
            const last = chart.data.datasets[0].data.at(-1);
            if (last) chartUpdates.push({canvas: chart.canvas.id, id: last.id, value: last.y});
        }});
    });
    const historyIds = () => page.locator('#history-body tr').evaluateAll(rows => rows.map(r => Number(r.dataset.readingId)));
    const assertHistory = async patientId => {
        const rows = await (await context.request.get(`${base}/api/patients/${patientId}/readings`)).json();
        await poll(async () => JSON.stringify(await historyIds()) === JSON.stringify(rows.map(r => r.id)), 'history IDs');
        const cells = await page.locator('#history-body tr').evaluateAll(rows => rows.map(r => [...r.cells].slice(1).map(c => c.textContent)));
        assert.deepEqual(cells, rows.map(r => [`${r.heart_rate} bpm`, `${Number(r.spo2.toFixed(1))}%`, `${r.temperature_c.toFixed(1)} °C`]));
        assert.deepEqual(await page.locator('#history-body time').evaluateAll(nodes => nodes.map(n => n.dateTime)), rows.map(r => r.recorded_at));
    };
    await assertHistory(a.id);
    const initialHistoryRows = (await historyIds()).length;
    await page.evaluate(() => {
        window.observedHistoryIds = new Set();
        new MutationObserver(() => document.querySelectorAll('#history-body tr').forEach(r => observedHistoryIds.add(Number(r.dataset.readingId))))
            .observe(document.querySelector('#history-body'), {childList: true});
    });
    const baseline = dbState(a.id);
    const before = count();
    const simulator = spawn(python, ['-m', 'app.simulator', '--patient-id', String(a.id), '--api-url', recorder.url, '--count', '10', '--interval', '0.5', '--seed', '42'], {env});
    let output = ''; simulator.stdout.on('data', chunk => output += chunk);
    const readings = 10;
    assert.equal((await once(simulator, 'close'))[0], 0);
    assert.equal((output.match(/HTTP 201/g) || []).length, readings);
    assert.equal(count() - before, readings);
    assert.equal(recorder.exchanges.length, readings);
    const printed = [...output.matchAll(/Patient (\d+) \| HR: (\d+) bpm \| SpO2: ([\d.]+)% \| Temp: ([\d.]+)°C \| HTTP 201/g)]
        .map(m => ({patient_id: +m[1], heart_rate: +m[2], spo2: +m[3], temperature_c: +m[4]}));
    assert.deepEqual(recorder.exchanges.map(e => e.payload), printed);
    for (const {payload, status, response} of recorder.exchanges) {
        assert.equal(status, 201);
        assert.deepEqual(Object.keys(response).sort(), ['id', 'patient_id', 'heart_rate', 'spo2', 'temperature_c', 'recorded_at'].sort());
        for (const key of Object.keys(payload)) assert.equal(response[key], payload[key]);
        assert(response.id > (baseline.latestId || 0));
        assert(Number.isFinite(Date.parse(response.recorded_at)));
    }
    assert.equal(new Set(recorder.exchanges.map(e => e.response.id)).size, readings);
    await poll(() => page.evaluate(n => testReadingEvents.length === n, readings), 'all live events');
    const events = await page.evaluate(() => testReadingEvents);
    const saved = JSON.parse(py(`import json
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Reading
from app.schemas import ReadingResponse
with SessionLocal() as db:
    rows = db.scalars(select(Reading).where(Reading.id.in_(${JSON.stringify(events.map(r => r.id))}))).all()
    print(json.dumps([ReadingResponse.model_validate(r).model_dump(mode='json') for r in rows]))`));
    assert.deepEqual(events.slice().sort((a,b) => a.id-b.id), saved.sort((a,b) => a.id-b.id));
    assert.deepEqual(recorder.exchanges.map(e => e.response), events);
    await assertHistory(a.id);
    const observedHistoryIds = await page.evaluate(() => [...observedHistoryIds]);
    for (const event of events) assert(observedHistoryIds.includes(event.id));
    const selectedOverview = page.locator(`.patient-button[data-patient-id="${a.id}"] .overview-vitals`);
    assert.equal(await selectedOverview.textContent(), `HR ${events.at(-1).heart_rate} bpm · SpO₂ ${events.at(-1).spo2}% · Temp ${events.at(-1).temperature_c.toFixed(1)} °C`);
    console.log(JSON.stringify({historySimulator: {initialRows: initialHistoryRows, sent: 10, newDatabaseRows: 10, observedNewRows: events.length, finalRows: (await historyIds()).length}}));
    const cardUpdates = await page.evaluate(() => cardUpdates);
    for (const event of events) assert(cardUpdates.some(card => card.id === event.id &&
        card.heart_rate === event.heart_rate && card.spo2 === event.spo2 &&
        card.temperature_c === event.temperature_c && card.recorded_at === event.recorded_at));
    const latest = await (await context.request.get(`${base}/api/patients/${a.id}/latest-reading`)).json();
    await poll(async () => await page.locator('#last-updated').getAttribute('datetime') === latest.recorded_at, 'simulator timestamp');
    assert.equal(await page.locator('#heart-rate').textContent(), String(latest.heart_rate));
    assert.equal(await page.locator('#spo2').textContent(), String(latest.spo2));
    assert.equal(await page.locator('#temperature').textContent(), latest.temperature_c.toFixed(1));
    await assertCharts(a.id);
    const chartUpdates = await page.evaluate(() => chartUpdates);
    for (const event of events) {
        for (const metric of ['heart_rate', 'spo2', 'temperature_c']) {
            assert(chartUpdates.some(update => update.canvas === `chart-${metric}` && update.id === event.id && update.value === event[metric]));
        }
    }
    const snapshot = () => page.evaluate(() => ({
        cards: ['heart-rate', 'spo2', 'temperature'].map(id => document.getElementById(id).textContent),
        time: document.getElementById('last-updated').dateTime,
        charts: ['heart_rate', 'spo2', 'temperature_c'].map(key => Chart.getChart(`chart-${key}`).data.datasets[0].data),
        events: testReadingEvents.length
    }));
    const stoppedSnapshot = await snapshot();
    await delay(600);
    assert.deepEqual(await snapshot(), stoppedSnapshot);
    assert.equal(await page.locator('#connection-status').textContent(), 'Connected');
    const unknownId = Number(py('from sqlalchemy import select, func; from app.database import SessionLocal; from app.models import Patient; db=SessionLocal(); print(db.scalar(select(func.max(Patient.id))) + 1); db.close()'));
    for (const [payload, expected] of [
        [{patient_id: a.id, heart_rate: -50, spo2: 150, temperature_c: 90}, 422],
        [{patient_id: unknownId, heart_rate: 78, spo2: 98, temperature_c: 36.8}, 404]
    ]) {
        const beforeFailure = dbState(null), ui = await snapshot();
        assert.equal((await context.request.post(`${base}/api/readings`, {data: payload})).status(), expected);
        await delay(300);
        assert.deepEqual(dbState(null), beforeFailure);
        assert.deepEqual(await snapshot(), ui);
    }
    if (!demo) {
        // Reload proves persisted data initializes all three charts.
        await page.reload();
        await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'reload');
        await assertCharts(a.id);
        // More live readings than the window: retain exactly the newest 20.
        for (let i = 0; i < 25; i++) {
            assert.equal((await context.request.post(`${base}/api/readings`, {data: {
                patient_id: a.id, heart_rate: 70 + i, spo2: 97 + i % 3, temperature_c: 36.5 + (i % 5) / 10
            }})).status(), 201);
        }
        await assertCharts(a.id);
        assert.equal((await chartData())[0].length, 20);
        // Duplicate delivery cannot add another point.
        const duplicate = await (await context.request.get(`${base}/api/patients/${a.id}/latest-reading`)).json();
        await page.evaluate(data => testSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: JSON.stringify({type: 'reading', data})})), duplicate);
        await assertCharts(a.id);
        // A snapshot started before a new live reading must not erase that reading.
        let snapshotReady = false;
        let releaseSnapshot;
        const release = new Promise(resolve => { releaseSnapshot = resolve; });
        await page.route(`**/api/patients/${a.id}/readings/recent`, async route => {
            const response = await route.fetch();
            snapshotReady = true;
            await release;
            await route.fulfill({response});
        }, {times: 1});
        await page.evaluate(() => testSockets.at(-1).close());
        await poll(() => snapshotReady, 'held reconnect snapshot');
        const duringRefresh = await (await context.request.post(`${base}/api/readings`, {data: {
            patient_id: a.id, heart_rate: 88, spo2: 98, temperature_c: 36.8
        }})).json();
        await poll(async () => (await chartData())[0].at(-1).id === duringRefresh.id, 'live event during refresh');
        releaseSnapshot();
        await delay(100);
        await assertCharts(a.id);
    }
    await page.screenshot({path: '/private/tmp/healthguard-dashboard-desktop.png', fullPage: true});
    await page.locator(`[data-patient-id="${b.id}"]`).click();
    await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'patient switch');
    assert.equal(await page.locator('#patient-name').textContent(), b.name);
    await assertCharts(b.id);
    await poll(() => page.evaluate(() => testSockets.filter(s => s.readyState < 2).length === 1), 'one subscription');
    assert(await page.evaluate(() => testSockets[0].readyState === 3));
    if (!demo) {
        await poll(async () => (await page.locator('#reading-state').textContent()).includes('No readings available'), 'empty patient');
        // Old subscription callbacks, wrong-patient payloads, malformed JSON and invalid values are ignored.
        await page.evaluate(({a, b}) => {
            const data = {id: 800, patient_id: a.id, heart_rate: 99, spo2: 99, temperature_c: 37, recorded_at: new Date().toISOString()};
            testSockets[0].dispatchEvent(new MessageEvent('message', {data: JSON.stringify({type: 'reading', data})}));
            testSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: JSON.stringify({type: 'reading', data})}));
            testSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: 'broken-json'}));
            data.patient_id = b.id; data.heart_rate = 'bad';
            testSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: JSON.stringify({type: 'reading', data})}));
        }, {a, b});
        assert.equal(await page.locator('#heart-rate').textContent(), '—');
        assert.equal((await chartData())[0].length, 0);
        // Drop the socket, persist a missed reading, then verify reconnect refreshes it.
        await page.evaluate(() => testSockets.at(-1).close());
        await poll(async () => (await page.locator('#connection-status').textContent()).includes('Reconnecting'), 'disconnect status');
        const response = await context.request.post(`${base}/api/readings`, {data: {patient_id: b.id, heart_rate: 84, spo2: 96, temperature_c: 37.1}});
        assert.equal(response.status(), 201);
        await poll(async () => await page.locator('#heart-rate').textContent() === '84', 'missed-reading recovery');
        assert.equal(await page.locator('#connection-status').textContent(), 'Connected');
        await assertCharts(b.id);
        const connectionsBefore = await page.evaluate(() => testSockets.length);
        await page.evaluate(() => testSockets.at(-1).close());
        await poll(() => page.evaluate(n => testSockets.length > n && testSockets.at(-1).readyState === 1, connectionsBefore), 'second reconnect');
        await assertCharts(b.id);
        assert.equal((await chartData())[0].length, 1);
        assert.equal(await page.evaluate(() => testSockets.filter(s => s.readyState < 2).length), 1);
        // A stale snapshot cannot overwrite a newer live event.
        assert.equal((await context.request.post(`${base}/api/readings`, {data: {
            patient_id: b.id, heart_rate: 60, spo2: 95, temperature_c: 36,
            recorded_at: '2020-01-01T00:00:00Z'
        }})).status(), 201);
        await assertCharts(b.id);
        assert.equal(await page.locator('#heart-rate').textContent(), '84');
        // Sub-millisecond measurement ordering takes precedence over insertion IDs.
        for (const [fraction, heart_rate] of [['000009', 92], ['000001', 91]]) {
            assert.equal((await context.request.post(`${base}/api/readings`, {data: {
                patient_id: b.id, heart_rate, spo2: 98, temperature_c: 36.8,
                recorded_at: `2040-01-01T00:00:00.${fraction}Z`
            }})).status(), 201);
        }
        await assertCharts(b.id);
        assert.equal(await page.locator('#heart-rate').textContent(), '92');
        // Cancel a pending retry when selecting another patient.
        await page.evaluate(() => testSockets.at(-1).close());
        await page.locator(`[data-patient-id="${a.id}"]`).click();
        await delay(1500);
        assert.equal(await page.evaluate(() => testSockets.filter(s => s.readyState < 2).length), 1);
        assert((await page.evaluate(() => testSockets.at(-1).url)).endsWith(`/patients/${a.id}`));
    }
    // Actual B simulator while monitoring A: neither events nor UI may change.
    await page.locator(`[data-patient-id="${a.id}"]`).click();
    await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'monitor A');
    await assertCharts(a.id);
    assert(await page.evaluate(id => testSockets.at(-1).readyState === 1 && testSockets.at(-1).url.endsWith(`/patients/${id}`), a.id));
    const aSnapshot = await snapshot(), bBefore = dbState(b.id);
    const second = spawn(python, ['-m', 'app.simulator', '--patient-id', String(b.id), '--api-url', recorder.url,
        '--count', '3', '--interval', '0.5', '--seed', '10'], {env});
    let secondOutput = ''; second.stdout.on('data', chunk => secondOutput += chunk);
    assert.equal((await once(second, 'close'))[0], 0);
    assert.equal((secondOutput.match(/HTTP 201/g) || []).length, 3);
    assert.equal(dbState(b.id).count - bBefore.count, 3);
    assert.deepEqual(await snapshot(), aSnapshot);
    for (const patient of [b, a]) {
        await page.locator(`[data-patient-id="${patient.id}"]`).click();
        await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'A/B switching');
        await assertCharts(patient.id);
        const stored = await (await context.request.get(`${base}/api/patients/${patient.id}/latest-reading`)).json();
        assert.equal(await page.locator('#patient-name').textContent(), patient.name);
        assert.equal(await page.locator('#heart-rate').textContent(), String(stored.heart_rate));
        assert.equal(await page.locator('#spo2').textContent(), String(Number(stored.spo2.toFixed(1))));
        assert.equal(await page.locator('#temperature').textContent(), stored.temperature_c.toFixed(1));
        await poll(() => page.evaluate(() => testSockets.filter(s => s.readyState < 2).length === 1), 'one active subscription');
    }
    await require('./dashboard_history.cjs')({page, context, base, a, b, poll, delay, assertHistory, historyIds});
    await require('./dashboard_alerts.cjs')({page, context, base, a, b, poll, delay, assertCharts, dbState, demo});
    await require('./dashboard_fuzzy.cjs')({page, context, base, a, b, poll, delay, assertHistory, assertCharts, python, env});
    await require('./dashboard_overview.cjs')({page, context, base, a, b, poll, delay, assertHistory, assertCharts});
    await require('./dashboard_states.cjs')({page, context, base, a, b, poll, delay, assertHistory, assertCharts});
    await page.setViewportSize({width: 1280, height: 720});
    await require('./dashboard_freshness.cjs')({page, context, base, a, poll, delay, assertHistory, assertCharts, python, env});
    await require('./dashboard_responsive.cjs')({page, context, base, a, b, poll, delay, assertHistory, assertCharts});
    assert.equal(await page.evaluate(() => Object.keys(Chart.instances).length), 3);
    await page.setViewportSize({width: 820, height: 1000});
    await poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'responsive canvas layout');
    await delay(300);
    await page.screenshot({path: '/private/tmp/healthguard-dashboard-tablet.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    await poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'responsive canvas layout');
    await delay(300); // Allow canvas ResizeObserver rendering before the full-page capture.
    await page.screenshot({path: '/private/tmp/healthguard-dashboard-mobile.png', fullPage: true});
    assert.deepEqual(errors, []);
    await page.getByRole('button', {name: 'Logout', exact: true}).click();
    await page.waitForURL('**/login');
    assert.equal(await page.evaluate(() => sessionStorage.getItem('freshnessTimersAfterLogout')), '0');
    await page.goto(`${base}/dashboard`);
    assert.equal(new URL(page.url()).pathname, '/login');
    console.log(JSON.stringify({mode: demo ? 'local demo' : 'isolated browser', baseline, finalReading: latest, consistency: 'all six stages matched', negativePaths: '422/404 no row/event/UI change', isolation: '3 B readings did not affect A', readings, http201: readings, newRows: readings, webSocketEvents: events.length, patientId: a.id, cards: 'matched saved data', chartUpdates: events.length * 3, charts: 'all three matched', rollingWindow: demo ? 'covered by isolated check' : 20, selection: 'passed', reconnect: demo ? 'covered by isolated check' : 'passed', logout: 'passed', consoleErrors: errors.length}));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
    if (browser) await browser.close();
    if (recorder) await recorder.close();
    if (server) { server.kill('SIGTERM'); await once(server, 'close'); }
    fs.rmSync(temp, {recursive: true, force: true});
});
