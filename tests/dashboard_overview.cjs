const assert=require('node:assert/strict');
module.exports=async({page,context,base,a,b,poll,delay,assertHistory,assertCharts})=>{
    const card=id=>page.locator(`.patient-button[data-patient-id="${id}"]`);
    const match=async id=>{
        await poll(async()=>{
            const values=await page.locator('.vital-value').allTextContents();
            return await card(id).locator('.overview-vitals').textContent()===`HR ${values[0]} bpm · SpO₂ ${values[1]}% · Temp ${values[2]} °C`;
        },'overview/main consistency');
        assert.equal(await card(id).locator('time').getAttribute('datetime'),await page.locator('#last-updated').getAttribute('datetime'));
        assert.equal(await card(id).getAttribute('aria-pressed'),'true');
        assert.equal(await card(id).locator('.overview-selected').textContent(),'Monitoring');
        assert.equal(await page.locator('.patient-button[aria-pressed="true"]').count(),1);
    };
    const select=async id=>{
        await card(id).click();
        await poll(async()=>await page.locator('#connection-status').textContent()==='Connected','overview selection');
        await assertCharts(id);await assertHistory(id);await match(id);
    };
    const post=async(id,hr=83)=>{
        const r=await context.request.post(`${base}/api/readings`,{data:{patient_id:id,heart_rate:hr,spo2:97,temperature_c:36.9}});
        assert.equal(r.status(),201);return r.json();
    };
    assert.equal(await page.getByRole('heading',{name:'Patient Overview',exact:true}).count(),1);
    assert.equal(await page.locator('.patient-button').count(),4);
    const ids=await page.locator('.patient-button').evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.patientId)));
    assert.match(await card(ids[2]).textContent(),/No readings yet/);
    await select(a.id);
    const beforeEvents=await page.evaluate(()=>testReadingEvents.length);
    const reading=await post(a.id);
    await poll(async()=>await page.locator('#heart-rate').textContent()==='83','overview live HR');
    await match(a.id);await assertCharts(a.id);await assertHistory(a.id);
    assert.equal(await page.evaluate(()=>testReadingEvents.length)-beforeEvents,1);
    const aSnapshot=await card(a.id).textContent(), bSnapshot=await card(b.id).textContent();
    await post(b.id,84);await delay(150);
    assert.equal(await card(a.id).textContent(),aSnapshot);
    assert.equal(await card(b.id).textContent(),bSnapshot);
    await select(b.id);
    await select(a.id);
    await post(a.id,110);
    await poll(async()=>await page.locator('#alert-state').getAttribute('data-state')==='data','overview alert refresh');
    assert.equal(await card(a.id).locator('.overview-alert-count').textContent(),await page.locator('#alert-count').textContent());
    for(const id of [b.id,ids[2],ids[3],a.id]) await card(id).click();
    await assertCharts(a.id);await assertHistory(a.id);await match(a.id);
    await poll(()=>page.evaluate(()=>testSockets.filter(s=>s.readyState<2).length===1),'single overview subscription');
    console.log(JSON.stringify({overview:'passed',patients:4,otherDoctor:0,liveReading:reading,readingEvents:1,counts:'match panel',rapidSwitch:'passed',snapshots:'unselected unchanged'}));
};
