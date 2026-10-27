/* Focused state verification using the shared authenticated browser/server fixture. */
const assert = require('node:assert/strict');
module.exports = async ({page, context, base, a, b, poll, delay, assertHistory, assertCharts}) => {
    await page.evaluate(() => {
        window.stateTestFetch = window.fetch;
        window.stateModes = {alerts:'pass',history:'pass'};
        window.stateHeld = [];
        window.fetch = async (...args) => {
            const url = String(args[0]);
            const section = /\/alerts$/.test(url) ? 'alerts' : /\/readings\?/.test(url) ? 'history' : null;
            if (!section) return stateTestFetch(...args);
            const mode = stateModes[section];
            if (mode === '500') return new Response('private server details', {status:500});
            if (mode === 'malformed') return new Response('{broken', {status:200});
            if (mode === 'empty') return new Response('[]', {status:200});
            if (mode === 'reject') throw new TypeError('Test connection failure');
            if (mode === 'hold') {
                // Deliberately ignore cancellation to test generation checks as well.
                const response = await stateTestFetch(args[0], {...args[1], signal:undefined});
                return new Promise(resolve => stateHeld.push({section, release:()=>resolve(response)}));
            }
            return stateTestFetch(...args);
        };
    });
    const modes = async (alerts='pass',history='pass') => page.evaluate(({alerts,history})=>{stateModes={alerts,history};},{alerts,history});
    const state = async (section, value) => poll(async()=>await page.locator(`#${section==='alerts'?'alert':'history'}-state`).getAttribute('data-state')===value, `${section} ${value}`);
    const select = async id => {
        await page.locator(`[data-patient-id="${id}"]`).click();
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','states connection');
    };
    const noRows = async section => assert.equal(await page.locator(section==='alerts'?'#alert-list li':'#history-body tr').count(),0);
    const post = async () => {
        const r=await context.request.post(`${base}/api/readings`,{data:{patient_id:a.id,heart_rate:110,spo2:90,temperature_c:39}});
        assert.equal(r.status(),201); return r.json();
    };
    try {
        for (const [name,width,height] of [['desktop',1280,720],['tablet',820,1000],['mobile',390,844]]) {
            await page.setViewportSize({width,height});
            await modes('hold','hold'); await select(a.id);
            await poll(()=>page.evaluate(()=>stateHeld.some(r=>r.section==='history')&&stateHeld.some(r=>r.section==='alerts')),'held sections');
            for(const section of ['alerts','history']) {await state(section,'loading'); await noRows(section);}
            assert.equal(await page.locator('#alert-count').textContent(),'0');
            await page.screenshot({path:`/private/tmp/healthguard-states-${name}-loading.png`,fullPage:true});
            await modes(); await page.evaluate(()=>{stateHeld.splice(0).forEach(r=>r.release());});
            await state('alerts','data'); await state('history','data');
            for(const failed of ['alerts','history']) {
                for(const mode of ['500','malformed','reject']) {
                    await modes(failed==='alerts'?mode:'pass',failed==='history'?mode:'pass');
                    await select(a.id);
                    await state(failed,'error'); await noRows(failed);
                    await state(failed==='alerts'?'history':'alerts','data');
                    assert.equal(await page.locator('#connection-status').textContent(),'Connected');
                    await assertCharts(a.id);
                }
            }
            await page.screenshot({path:`/private/tmp/healthguard-states-${name}-error.png`,fullPage:true});
            await modes('empty','empty'); await select(a.id);
            for(const section of ['alerts','history']) {await state(section,'empty'); await noRows(section);}
            await page.screenshot({path:`/private/tmp/healthguard-states-${name}-empty.png`,fullPage:true});
            assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
            await modes(); await select(a.id);
            await state('alerts','data'); await assertHistory(a.id);
        }
        // Hold BOTH A responses, switch rapidly through B and Arjun and back to A.
        const ids=await page.locator('.patient-button').evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.patientId)));
        await modes('hold','hold'); await select(a.id);
        await poll(()=>page.evaluate(()=>stateHeld.length>=2),'old A snapshots');
        await modes();
        for(const id of [b.id,ids[2],a.id,b.id]) await page.locator(`[data-patient-id="${id}"]`).click();
        await assertHistory(b.id); await state('alerts','data');
        const before=await page.locator('#alert-list').textContent();
        await page.evaluate(()=>{stateHeld.splice(0).forEach(r=>r.release());}); await delay(100);
        await assertHistory(b.id); assert.equal(await page.locator('#alert-list').textContent(),before);
        await select(a.id); await assertHistory(a.id);
        // Older history snapshot cannot erase a reading committed while it was held.
        await modes('pass','hold'); await select(a.id);
        await poll(()=>page.evaluate(()=>stateHeld.some(r=>r.section==='history')),'history loading snapshot');
        const live=await post();
        await poll(async()=>await page.locator(`#history-body tr[data-reading-id="${live.id}"]`).count()===1,'live during loading');
        await modes(); await page.evaluate(()=>{stateHeld.splice(0).forEach(r=>r.release());});
        await assertHistory(a.id);
        assert.equal(await page.locator(`#history-body tr[data-reading-id="${live.id}"]`).count(),1);
        await assertCharts(a.id);
        // Reconnect while one auxiliary API fails, with continued real live updates.
        await modes('500','pass');
        await page.evaluate(()=>testSockets.at(-1).close());
        await poll(async()=>(await page.locator('#connection-status').textContent()).includes('Reconnecting'),'state reconnect');
        await post();
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','state reconnect complete');
        await state('alerts','error'); await assertHistory(a.id); await assertCharts(a.id);
        assert.equal(await page.locator('#heart-rate').textContent(),'110');
        await modes(); await select(a.id); await state('alerts','data'); await assertHistory(a.id);
        console.log(JSON.stringify({sectionStates:'all four passed',failures:'500/malformed/network isolated',rapidSwitch:'passed',liveDuringLoad:'retained once',reconnectFailure:'isolated',viewports:'desktop/tablet/mobile'}));
    } finally {
        await page.evaluate(()=>{window.fetch=stateTestFetch;stateHeld.splice(0).forEach(r=>r.release());});
        await page.setViewportSize({width:1440,height:1000});
    }
};
