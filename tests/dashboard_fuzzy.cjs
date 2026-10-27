/* Academic software assessment only; real API/persistence and reading stream. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
module.exports = async ({page, context, base, a, b, poll, delay, assertHistory, assertCharts, python, env}) => {
    const endpoint = id => `${base}/api/patients/${id}/fuzzy-assessment`;
    const check = async id => {
        const response = await context.request.get(endpoint(id));
        assert.equal(response.status(), 200);
        const data = await response.json();
        if (!data.assessment) {
            await poll(async()=>await page.locator('#fuzzy-state').getAttribute('data-state')==='empty','fuzzy empty');
            assert.equal(await page.locator('#fuzzy-content').isVisible(),false);
            assert.match(await page.locator('#fuzzy-state').textContent(),/A sensor reading is required/);
        } else {
            await poll(async()=>await page.locator('#fuzzy-content').getAttribute('data-reading-id')===String(data.reading_id),'fuzzy latest reading');
            assert.equal(await page.locator('#fuzzy-score').textContent(),data.assessment.risk_score.toFixed(1));
            assert.equal(await page.locator('#fuzzy-status').textContent(),{normal:'Normal',warning:'Warning',critical:'Critical demo status'}[data.assessment.status]);
            assert.deepEqual(await page.locator('#fuzzy-outputs progress').evaluateAll(nodes=>nodes.map(n=>n.value)),Object.values(data.assessment.output_memberships));
            assert.equal(await page.locator('#fuzzy-inputs progress').count(),8);
            assert.deepEqual(await page.locator('#fuzzy-inputs progress').evaluateAll(nodes=>nodes.map(n=>n.value)), Object.values(data.assessment.input_memberships).flatMap(group=>Object.values(group))); 
            assert.equal(await page.locator('#fuzzy-time').getAttribute('datetime'),data.recorded_at);
        }
        return data;
    };
    const select = async id => {
        await page.locator(`.patient-button[data-patient-id="${id}"]`).click();
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','fuzzy selection connected');
        return check(id);
    };
    const post = async hr => {
        const r=await context.request.post(`${base}/api/readings`,{data:{patient_id:a.id,heart_rate:hr,spo2:98,temperature_c:36.8}});
        assert.equal(r.status(),201); return r.json();
    };
    const ids=await page.locator('.patient-button').evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.patientId)));
    await select(ids[2]); // still unused in the isolated fixture at this point
    await select(a.id);
    await page.locator('.fuzzy-panel summary').click();
    assert.equal(await page.locator('#fuzzy-inputs').isVisible(),true);
    // Hold a real response *after* fetching, deliberately ignoring AbortController.
    const hold = async () => page.evaluate(id=>{
        window.originalFuzzyFetch=window.fetch;
        window.fuzzyHeld=false;
        let once=true;
        window.fetch=async(...args)=>{
            const response=await originalFuzzyFetch(...args);
            if(once && String(args[0]).includes(`/patients/${id}/fuzzy-assessment`)) {
                const body=await response.text();
                if (!once) return new Response(body,{status:200});
                once=false;
                fuzzyHeld=true;
                await new Promise(resolve=>window.releaseFuzzy=resolve);
                return new Response(body,{status:200,headers:{'Content-Type':'application/json'}});
            }
            return response;
        };
    },a.id);
    await hold();
    await page.locator(`.patient-button[data-patient-id="${a.id}"]`).click();
    await poll(()=>page.evaluate(()=>fuzzyHeld),'held old-patient response');
    await select(b.id);
    const bText=await page.locator('#fuzzy-content').textContent();
    await page.evaluate(()=>releaseFuzzy()); await delay(150);
    assert.equal(await page.locator('#fuzzy-content').textContent(),bText);
    await page.evaluate(()=>window.fetch=originalFuzzyFetch);
    await select(a.id);
    // A slow old result cannot overwrite a refresh triggered by a newer reading.
    await hold();
    await post(94);
    await poll(()=>page.evaluate(()=>fuzzyHeld),'held live assessment');
    assert.equal(await page.locator('#fuzzy-state').getAttribute('data-state'),'loading');
    assert.equal(await page.locator('#fuzzy-content').isVisible(),false);
    const newer=await post(110);
    await check(a.id);
    await page.evaluate(()=>releaseFuzzy()); await delay(150);
    assert.equal(await page.locator('#fuzzy-content').getAttribute('data-reading-id'),String(newer.id));
    await page.evaluate(()=>window.fetch=originalFuzzyFetch);
    // API errors and malformed bodies must stay local to this panel.
    for (const kind of ['network','500','malformed']) {
        await page.evaluate(kind=>{
            window.originalFuzzyFetch=window.fetch;
            window.fetch=(...args)=>String(args[0]).includes('/fuzzy-assessment') ?
                kind==='network' ? Promise.reject(new TypeError('test network failure')) :
                Promise.resolve(new Response(kind==='500'?'error':'{}',{status:kind==='500'?500:200})) : originalFuzzyFetch(...args);
        },kind);
        await page.locator(`.patient-button[data-patient-id="${a.id}"]`).click();
        await poll(async()=>await page.locator('#fuzzy-state').getAttribute('data-state')==='error','fuzzy error');
        assert.equal(await page.locator('#fuzzy-state').textContent(),'Unable to load fuzzy assessment.');
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','independent websocket');
        await post(83);
        await poll(async()=>await page.locator('#heart-rate').textContent()==='83','independent cards');
        await assertHistory(a.id); await assertCharts(a.id);
        await poll(async()=>await page.locator('#alert-state').getAttribute('data-state')==='data','independent alerts');
        await page.evaluate(()=>window.fetch=originalFuzzyFetch);
    }
    await select(a.id);
    await page.evaluate(()=>{
        window.fuzzyObserved=new Set();
        new MutationObserver(()=>{const id=document.getElementById('fuzzy-content').dataset.readingId;if(id) fuzzyObserved.add(Number(id));})
            .observe(document.getElementById('fuzzy-content'),{attributes:true,attributeFilter:['data-reading-id']});
    });
    const beforeEvents=await page.evaluate(()=>testReadingEvents.length);
    const child=spawn(python,['-m','app.simulator','--patient-id',String(a.id),'--api-url',`${base}/api/readings`,'--count','5','--interval','1','--seed','42'],{env});
    let output=''; child.stdout.on('data',d=>output+=d);
    assert.equal((await once(child,'close'))[0],0);
    assert.equal((output.match(/HTTP 201/g)||[]).length,5);
    await check(a.id); await assertCharts(a.id); await assertHistory(a.id);
    const events=await page.evaluate(n=>testReadingEvents.slice(n),beforeEvents);
    assert.equal(events.length,5);
    const observed=await page.evaluate(()=>[...fuzzyObserved]);
    for(const r of events) assert(observed.includes(r.id));
    const stored=await (await context.request.get(`${base}/api/patients/${a.id}/readings`)).json();
    for(const r of events) assert(stored.some(s=>s.id===r.id));
    await page.evaluate(()=>testSockets.at(-1).close());
    await poll(async()=>(await page.locator('#connection-status').textContent()).includes('Reconnecting'),'fuzzy reconnect starts');
    const missed=await post(94);
    await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','fuzzy reconnect connected');
    await check(a.id); await assertHistory(a.id); await assertCharts(a.id);
    assert.equal(await page.locator('#fuzzy-content').getAttribute('data-reading-id'),String(missed.id));
    for(const [width,height] of [[1440,900],[820,1000],[390,844]]) {
        await page.setViewportSize({width,height}); await delay(150);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await page.locator('.fuzzy-panel').screenshot({path:`/private/tmp/healthguard-fuzzy-${width}.png`});
    }
    console.log(JSON.stringify({fuzzy:'passed',states:'loading/data/empty/error',stalePatient:'ignored',staleLive:'ignored',reconnect:'recovered latest persisted assessment',simulator201:5,readingEvents:5,assessmentsObserved:5,historyCharts:'matched',viewports:'desktop/tablet/mobile'}));
};
