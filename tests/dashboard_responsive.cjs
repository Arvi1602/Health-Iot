/* Called by dashboard_browser.cjs: reuse its real login, SQLite and WebSocket fixture. */
const assert = require('node:assert/strict');
module.exports = async ({page, context, base, a, b, poll, delay, assertHistory, assertCharts}) => {
    const viewports = [[1280,720],[1366,768],[1440,900],[1536,864],[1920,1080],[2560,1440]];
    const bounds = async () => {
        const issues = await page.evaluate(() => {
            const problems = [], width = document.documentElement.clientWidth;
            if (document.documentElement.scrollWidth > width || document.body.scrollWidth > width) problems.push('page overflow');
            const selectors = ['.site-header','.brand','#logout-form button','.patient-panel','.patient-button',
                '.monitor-heading','#patient-name','.monitor-statuses','#connection-status','#data-freshness',
                '.vital-card','.chart-card','.chart-container canvas','.demo-alerts','.alert-item','.history-scroll'];
            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0 || r.left < -2 || r.right > width + 2) problems.push(`${selector}: bounds`);
                    if (selector !== '.history-scroll' && el.scrollWidth > el.clientWidth + 2) problems.push(`${selector}: content overflow`);
                }
            }
            const childrenOverlap = selector => {
                const boxes = [...document.querySelector(selector).children].map(el => el.getBoundingClientRect());
                return boxes.some((a,i) => boxes.slice(i+1).some(b =>
                    Math.min(a.right,b.right)-Math.max(a.left,b.left)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2));
            };
            for (const selector of ['.site-header','.monitor-heading','.patient-list','.vital-grid','.chart-grid']) {
                if (childrenOverlap(selector)) problems.push(`${selector}: overlap`);
            }
            for (const canvas of document.querySelectorAll('.chart-container canvas')) {
                const r = canvas.getBoundingClientRect(), parent = canvas.parentElement.getBoundingClientRect();
                if (r.right > parent.right + 2 || r.height < 180 || r.height > parent.height + 2) problems.push('chart sizing');
            }
            if (visualViewport.scale !== 1) problems.push('unexpected zoom');
            return problems;
        });
        assert.deepEqual(issues, [], `layout at ${JSON.stringify(page.viewportSize())}`);
    };
    const select = async id => {
        await page.locator(`[data-patient-id="${id}"]`).click();
        await poll(async () => await page.locator('#connection-status').textContent() === 'Connected', 'responsive selection');
        await assertHistory(id); await assertCharts(id);
        assert.equal(await page.locator('.patient-button[aria-pressed="true"]').getAttribute('data-patient-id'), String(id));
    };
    await page.setViewportSize({width:1280,height:720});
    for (const id of [b.id,a.id,b.id,a.id]) await select(id);
    // Keyboard activation follows the same existing selection lifecycle.
    await page.locator('#logout-form button').focus();
    await page.keyboard.press('Tab');
    assert(await page.locator('.patient-button').first().evaluate(el => el === document.activeElement && el.matches(':focus-visible')));
    await page.keyboard.press('Enter');
    await assertHistory(a.id);
    await page.keyboard.press('Shift+Tab');
    assert(await page.locator('#logout-form button').evaluate(el => el === document.activeElement && el.matches(':focus-visible')));
    const chartIds = await page.evaluate(() => Object.keys(Chart.instances));
    for (const [width,height] of viewports) {
        await page.setViewportSize({width,height});
        await delay(300); // Let Chart.js ResizeObserver settle.
        for (const selector of ['.patient-panel','#patient-name','#heart-rate','#spo2','#temperature',
            '#connection-status','#data-freshness','.trends','.demo-alerts','.reading-history','#logout-form button']) {
            assert(await page.locator(selector).isVisible(), selector);
        }
        if (width <= 1366) {
            const response = await context.request.post(`${base}/api/readings`, {data:{
                patient_id:a.id,heart_rate:width===1280?100:110,spo2:width===1280?96:90,temperature_c:width===1280?37.4:39
            }});
            assert.equal(response.status(),201);
            const reading = await response.json();
            await poll(async () => await page.locator('#heart-rate').textContent() === String(reading.heart_rate), 'responsive live card');
            await assertCharts(a.id); await assertHistory(a.id);
            await poll(async () => await page.locator('#alert-state').getAttribute('data-state') === 'data', 'responsive stored alerts');
        }
        await bounds();
        await page.locator('.reading-history').scrollIntoViewIfNeeded();
        assert(await page.evaluate(() => scrollY > 0), 'vertical scrolling');
        await page.locator('#logout-form button').scrollIntoViewIfNeeded();
        await page.screenshot({path:`/private/tmp/task019-${width}x${height}.png`,fullPage:true});
        // Text-only robustness fixtures; never used as evidence of live data correctness.
        const selectors = ['.dashboard > .subtitle','.overview-heading strong','#patient-name','.alert-item p','#connection-status'];
        const originals = await Promise.all(selectors.map(s => page.locator(s).first().textContent()));
        await page.evaluate(selectors => {
            const text = ['Welcome, Dr. Alexandra Elizabeth Ramanathan Subramanian',
                'Alexandra Elizabeth Ramanathan Subramanian','Alexandra Elizabeth Ramanathan Subramanian',
                'Reading crossed a configured academic demo threshold. This longer explanation tests wrapping without truncating the stored alert message. '.repeat(3),
                'Reconnecting…'];
            selectors.forEach((s,i) => document.querySelector(s).textContent = text[i]);
        }, selectors);
        await bounds();
        await page.screenshot({path:`/private/tmp/task019-${width}x${height}-long-text.png`,fullPage:true});
        await page.evaluate(({selectors,originals}) => selectors.forEach((s,i) => document.querySelector(s).textContent=originals[i]), {selectors,originals});
        assert.deepEqual(await page.evaluate(() => Object.keys(Chart.instances)), chartIds, 'resize retains chart instances');
    }
    console.log(JSON.stringify({responsive:'passed',viewports,overflow:'none',keyboard:'passed',switching1280:'passed',liveReadingsAndAlerts:'passed',longText:'passed',chartInstances:'retained'}));
};
