const assert = require('node:assert/strict');
module.exports = async ({page, context, base, a, b, poll, delay, assertHistory, historyIds}) => {
    const select = async id => {
        await page.locator(`[data-patient-id="${id}"]`).click();
        await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'history connection');
        await assertHistory(id);
    };
    const post = async id => {
        const response = await context.request.post(`${base}/api/readings`, {data: {patient_id:id,heart_rate:79,spo2:98,temperature_c:36.8}});
        assert.equal(response.status(),201); return response.json();
    };
    await assertHistory(a.id);
    const before = await historyIds();
    await post(b.id); await delay(150);
    assert.deepEqual(await historyIds(), before);
    await select(b.id); await select(a.id);
    // Initial empty state on a seeded patient never used by this test.
    const ids = await page.locator('.patient-button').evaluateAll(nodes => nodes.map(n => Number(n.dataset.patientId)));
    await select(ids[2]);
    if (!(await historyIds()).length) assert.equal(await page.locator('#history-state').textContent(), 'No readings available for this patient yet.');
    await select(a.id);
    let held = false, release;
    const gate = new Promise(resolve => {release=resolve;});
    await page.route(`**/api/patients/${a.id}/readings?*`, async route => {
        const response = await route.fetch(); held=true; await gate;
        await route.fulfill({response}).catch(()=>{});
    });
    await page.locator(`[data-patient-id="${a.id}"]`).click();
    await poll(()=>held,'held history');
    assert.equal((await historyIds()).length,0);
    assert.match(await page.locator('#history-state').textContent(),/Loading/);
    await select(b.id);
    const bRows = await historyIds(); release(); await delay(150);
    assert.deepEqual(await historyIds(), bRows);
    await page.unroute(`**/api/patients/${a.id}/readings?*`);
    await select(a.id);
    // Reconnect recovers a reading stored during the gap exactly once.
    await page.evaluate(()=>testSockets.at(-1).close());
    await poll(async()=>(await page.locator('#connection-status').textContent()).includes('Reconnecting'),'history disconnect');
    const missed = await post(a.id);
    await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','history reconnect');
    await assertHistory(a.id);
    assert.equal((await historyIds()).filter(id=>id===missed.id).length,1);
    await page.evaluate(data=>testSockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'reading',data})})),missed);
    await assertHistory(a.id);
    assert.equal((await historyIds()).filter(id=>id===missed.id).length,1);
    // History fetch failure must not stop the independent panels or live subscription.
    await page.evaluate(()=>{
        window.historyTestFetch=window.fetch;
        window.fetch=(...args)=>/\/readings\?/.test(String(args[0])) ? Promise.reject(new TypeError('test network failure')) : historyTestFetch(...args);
    });
    await page.locator(`[data-patient-id="${a.id}"]`).click();
    await poll(async()=>(await page.locator('#history-state').textContent()).includes('Unable to load'),'history error');
    await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','error independent connection');
    await post(a.id);
    await poll(async()=>await page.locator('#heart-rate').textContent()==='79','cards after error');
    await page.evaluate(()=>{window.fetch=historyTestFetch;});
    await select(a.id);
    // Bounded table after many real POSTs, preserving server timestamp/id ordering.
    for(let i=0;i<21;i++) await post(a.id);
    await assertHistory(a.id);
    assert.equal((await historyIds()).length,20);
    console.log(JSON.stringify({history:'passed', isolation:'passed', staleResponse:'passed', reconnect:{missed:1,recovered:1,duplicates:0},error:'contained',limit:20}));
};
