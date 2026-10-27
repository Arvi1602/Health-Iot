/* TASK-014 checks reuse the existing real server, login, browser and SQLite fixture. */
const assert = require('node:assert/strict');
module.exports = async ({page, context, base, a, b, poll, delay, assertCharts, dbState, demo}) => {
    const api = async id => (await context.request.get(`${base}/api/patients/${id}/alerts`)).json();
    const shown = () => page.locator('#alert-list .alert-item p').allTextContents();
    const check = async id => {
        const alerts = (await api(id)).slice(0, 10);
        await poll(async () => JSON.stringify(await shown()) === JSON.stringify(alerts.map(a => a.message)), 'stored alert messages');
        assert.equal(await page.locator('#alert-count').textContent(), String(alerts.length));
        assert.deepEqual(await page.locator('#alert-list time').evaluateAll(nodes => nodes.map(n => n.dateTime)), alerts.map(a => a.created_at));
        assert.deepEqual(await page.locator('#alert-list time').evaluateAll(nodes => nodes.map(n => n.textContent)), await page.evaluate(rows => rows.map(a => new Date(a.created_at).toLocaleString()), alerts));
        return alerts;
    };
    const select = async id => {
        await page.locator(`[data-patient-id="${id}"]`).click();
        await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'alert patient connection');
        await check(id);
    };
    const post = async (id, values = {}) => {
        const response = await context.request.post(`${base}/api/readings`, {data: {patient_id: id, heart_rate: 78, spo2: 98, temperature_c: 36.8, ...values}});
        assert.equal(response.status(), 201);
        return response.json();
    };
    await check(a.id);
    if (!demo) assert.equal(await page.locator('#alert-state').textContent(), 'No demo threshold alerts for this patient.');
    const before = (await api(a.id)).length;
    await post(a.id, {heart_rate: 101});
    await poll(async () => (await shown()).length === Math.min(before + 1, 10), 'single live alert');
    await check(a.id);
    const rowsBefore = dbState(a.id).count;
    const eventsBefore = await page.evaluate(() => testReadingEvents.length);
    const alertsBefore = (await api(a.id)).length;
    const reading = await post(a.id, {heart_rate: 110, spo2: 90, temperature_c: 39});
    await check(a.id);
    assert.equal(dbState(a.id).count - rowsBefore, 1);
    const generated = (await api(a.id)).filter(a => a.reading_id === reading.id);
    assert.deepEqual(generated.map(a => a.alert_type).sort(), ['heart_rate_high', 'spo2_low', 'temperature_high']);
    await poll(() => page.evaluate(n => testReadingEvents.length === n, eventsBefore + 1), 'one reading event');
    assert.equal(await page.locator('#heart-rate').textContent(), '110');
    assert.equal(await page.locator('#spo2').textContent(), '90');
    assert.equal(await page.locator('#temperature').textContent(), '39.0');
    await assertCharts(a.id);
    const savedAlerts = await shown();
    await post(a.id);
    await poll(async () => await page.locator('#heart-rate').textContent() === '78', 'normal card update');
    await check(a.id);
    assert.deepEqual(await shown(), savedAlerts);
    const isolated = await shown();
    const aCards = await page.locator('.vital-value').allTextContents();
    await post(b.id, {spo2: 90});
    await delay(200);
    assert.deepEqual(await shown(), isolated);
    assert.deepEqual(await page.locator('.vital-value').allTextContents(), aCards);
    await select(b.id);
    await select(a.id);

    // Hold an old patient's response through A -> B -> A -> B switching.
    let held = false, release;
    const gate = new Promise(resolve => { release = resolve; });
    await page.route(`**/api/patients/${a.id}/alerts`, async route => {
        const response = await route.fetch(); held = true;
        await gate;
        await route.fulfill({response}).catch(() => {}); // Request may be aborted by selection.
    });
    await select(b.id);
    await page.locator(`[data-patient-id="${a.id}"]`).click();
    await poll(() => held, 'held alert response');
    assert.equal(await page.locator('#alert-list li').count(), 0);
    assert.match(await page.locator('#alert-state').textContent(), /Loading alerts/);
    await select(b.id);
    const bMessages = await shown();
    release(); await delay(200);
    assert.deepEqual(await shown(), bMessages);
    await page.unroute(`**/api/patients/${a.id}/alerts`);
    await select(a.id);

    // A slow older refresh for the same patient must not replace newer results.
    let oldReady = false, releaseOld;
    const oldGate = new Promise(resolve => { releaseOld = resolve; });
    await page.route(`**/api/patients/${a.id}/alerts`, async route => {
        const response = await route.fetch(); oldReady = true;
        await oldGate;
        await route.fulfill({response}).catch(() => {});
    }, {times: 1});
    await post(a.id);
    await poll(() => oldReady, 'older same-patient response');
    await post(a.id, {heart_rate: 103});
    await check(a.id);
    const newestMessages = await shown();
    releaseOld(); await delay(200);
    assert.deepEqual(await shown(), newestMessages);

    // Network rejection is simulated at fetch, without injecting any dashboard data.
    await page.evaluate(() => {
        window.originalAlertTestFetch = window.fetch;
        window.fetch = (...args) => String(args[0]).endsWith('/alerts') ? Promise.reject(new TypeError('Test network failure')) : originalAlertTestFetch(...args);
    });
    await post(a.id, {heart_rate: 80});
    await poll(async () => (await page.locator('#alert-state').textContent()).includes('Unable to load'), 'alert error state');
    assert.equal(await page.locator('#heart-rate').textContent(), '80');
    assert.equal(await page.locator('#connection-status').textContent(), 'Connected');
    await assertCharts(a.id);
    await page.evaluate(() => { window.fetch = originalAlertTestFetch; });
    // A missed alert during disconnection is recovered on the connected acknowledgement.
    await page.evaluate(() => testSockets.at(-1).close());
    await poll(async () => (await page.locator('#connection-status').textContent()).includes('Reconnecting'), 'alert reconnect');
    await post(a.id, {heart_rate: 102});
    await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'alert recovery');
    await check(a.id);
    for (let i = 0; i < 4; i++) await post(a.id, {heart_rate: 110, spo2: 90, temperature_c: 39});
    await check(a.id);
    assert.equal(await page.locator('#alert-list li').count(), 10);
    assert.equal(await page.locator('#alert-state').textContent(), 'Showing latest 10 demo alerts');
    await page.reload();
    await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'initial stored alerts');
    await check(a.id);
    await assertCharts(a.id);
    await page.screenshot({path: '/private/tmp/healthguard-dashboard-desktop.png', fullPage: true});
    console.log(JSON.stringify({alertPanel:'passed', normal:'stored alerts retained', single:'passed', multi:{readings:1,alerts:3,readingEvents:1,itemsAdded:Math.min(alertsBefore+3,10)-Math.min(alertsBefore,10)}, isolation:'passed', switchingRace:'passed', networkFailure:'contained', reconnect:'recovered', limit:10}));
};
