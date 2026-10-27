const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
module.exports=async({page,context,base,a,poll,delay,assertHistory,assertCharts,python,env})=>{
    const state=async expected=>poll(async()=>await page.locator('#data-freshness').getAttribute('data-state')===expected,`freshness ${expected}`);
    const select=async id=>{
        await page.locator(`[data-patient-id="${id}"]`).click();
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','freshness connection');
        await assertHistory(id);await assertCharts(id);
    };
    const post=async(id,timestamp)=>{
        const data={patient_id:id,heart_rate:78,spo2:98,temperature_c:36.8};
        if(timestamp)data.recorded_at=timestamp;
        const r=await context.request.post(`${base}/api/readings`,{data});assert.equal(r.status(),201);return r.json();
    };
    await select(a.id);
    const runSimulator=async count=>{
        const child=spawn(python,['-m','app.simulator','--patient-id',String(a.id),'--api-url',`${base}/api/readings`,'--count',String(count),'--interval','1','--seed','42'],{env});
        let output='';child.stdout.on('data',d=>output+=d);
        assert.equal((await once(child,'close'))[0],0);
        assert.equal((output.match(/HTTP 201/g)||[]).length,count);
    };
    await runSimulator(3);await state('fresh');
    const timestamp=await page.locator('#last-updated').getAttribute('datetime');
    const alertRows=await (await context.request.get(`${base}/api/patients/${a.id}/alerts`)).json();
    await delay(11000);await state('stale');
    assert.equal(await page.locator('#connection-status').textContent(),'Connected');
    assert.equal(await page.locator('#last-updated').getAttribute('datetime'),timestamp);
    assert.deepEqual(await (await context.request.get(`${base}/api/patients/${a.id}/alerts`)).json(),alertRows);
    await runSimulator(1);await state('fresh');
    const recent=await post(a.id);
    await poll(async()=>await page.locator('#last-updated').getAttribute('datetime')===recent.recorded_at,'latest timestamp');
    // Control comparison clock, not the measurement or UI, for exact boundaries.
    await page.evaluate(()=>{window.realFreshnessNow=Date.now;});
    for(const [age,expected] of [[10000,'fresh'],[10001,'stale'],[-5000,'fresh']]){
        await page.evaluate(({timestamp,age})=>{Date.now=()=>Date.parse(timestamp)+age;document.dispatchEvent(new Event('visibilitychange'));},{timestamp:recent.recorded_at,age});
        await state(expected);
    }
    await page.evaluate(()=>{Date.now=realFreshnessNow;document.dispatchEvent(new Event('visibilitychange'));});
    await state('fresh');
    // Model a server policy close after a real socket shutdown. Browsers cannot send 1008.
    await page.evaluate(()=>{
        const socket=testSockets.at(-1), onclose=socket.onclose;
        socket.onclose=()=>onclose(new CloseEvent('close',{code:1008}));
        socket.close();
    });
    await poll(async()=>await page.locator('#connection-status').textContent()==='Disconnected','disconnected');
    await state('fresh');await delay(11000);await state('stale');
    assert.equal(await page.locator('#last-updated').getAttribute('datetime'),recent.recorded_at);
    await select(a.id);await state('stale'); // Reconnect alone cannot make old data fresh.
    await post(a.id);await state('fresh');
    await page.evaluate(()=>testSockets.at(-1).close());
    await poll(async()=>(await page.locator('#connection-status').textContent()).includes('Reconnecting'),'reconnecting');
    const missed=await post(a.id);
    await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','recovered');
    await state('fresh');await assertHistory(a.id);await assertCharts(a.id);
    assert.equal(await page.locator(`#history-body tr[data-reading-id="${missed.id}"]`).count(),1);
    const ids=await page.locator('.patient-button').evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.patientId)));
    await post(ids[2],new Date(Date.now()-30000).toISOString());
    await select(ids[2]);await state('stale');
    await select(a.id);await post(a.id);await state('fresh');
    await select(ids[3]);await state('no-data');
    for(const id of [a.id,ids[2],ids[3],a.id])await select(id);
    assert.equal(await page.evaluate(()=>activeFreshnessTimers.size),1);
    const before=await page.locator('#last-updated').getAttribute('datetime');
    await post(a.id,'2020-01-01T00:00:00Z');await delay(100);
    assert.equal(await page.locator('#last-updated').getAttribute('datetime'),before);
    await page.evaluate(id=>testSockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'reading',data:{id:99999,patient_id:id,heart_rate:78,spo2:98,temperature_c:36.8,recorded_at:'invalid'}})})),a.id);
    assert.equal(await page.locator('#last-updated').getAttribute('datetime'),before);
    await page.screenshot({path:'/private/tmp/healthguard-freshness-desktop.png',fullPage:true});
    // Record cleanup after the application's existing submit listener runs.
    await page.evaluate(()=>document.querySelector('#logout-form').addEventListener('submit',()=>sessionStorage.setItem('freshnessTimersAfterLogout',String(activeFreshnessTimers.size))));
    console.log(JSON.stringify({freshness:'passed',simulatorStop:'connected/stale',resume:'connected/fresh',boundary:'10000 fresh;10001 stale',clockSkew:'clamped',disconnect:'fresh then stale',reconnect:'recovered',switching:'fresh/stale/no-data',timers:1,invalidEvent:'ignored',alerts:'unchanged while aging'}));
};
