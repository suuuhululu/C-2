// Execute the production app against small HTTP/DOM fixtures, without a browser or DB.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('history/web_assets/app.js', 'utf8');
const jobId = '91f500fc-2cb4-4f98-b6fc-97b2ac26c30d';
const identity = {username:'fixture_creator', display_name:'Fixture creator'};
const designEntries = [1,2,3].map(version => ({
  job_id:jobId, design_version:version, adopted_at:'2026-10-12T00:00:00Z',
  creator:identity, published:false,
  design:{design_version:version, blocks:[{brick_type:'2x2x1',color:'blue',x:4,y:4,layer:1,orientation_deg:0}]}
}));
const timeline = Array.from({length:9}, (_,index) => ({
  event:'MOTION_SAMPLE', occurred_at:'2026-10-12T00:00:00Z', reason:null,
  document:{result:{sample_index:index}}
}));
const fullRecord = {
  owner:{job_id:jobId},
  jobs:[{job_id:jobId,result:'NO_COMPLETION_RECORDED',started_at:'2026-10-12T00:00:00Z',last_seen_at:'2026-10-12T00:00:00Z'}],
  designs:designEntries, plans:[], currents:[], checks:[], hri:[],
  completion:{work_exhaustion:'NOT_RECORDED'}, storage:{status:'PENDING'}, timeline
};
const summaryRecord = {...fullRecord, timeline:timeline.slice(-2), timeline_total:timeline.length};
const clone = value => JSON.parse(JSON.stringify(value));
const flatten = value => [value,...value.children.flatMap(flatten)];
const flush = () => new Promise(resolve => setImmediate(resolve));

function element(tag) {
  const classes = new Set();
  return {
    tag, attrs:{}, children:[], listeners:{}, dataset:{}, value:'', open:false, disabled:false,
    setAttribute(key,value) { this.attrs[key] = String(value); },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(type,fn) { (this.listeners[type] ??= []).push(fn); },
    async emit(type, event={}) { for (const fn of this.listeners[type] ?? []) await fn(event); },
    showModal() { this.open = true; },
    close() {
      if (!this.open) return;
      this.open = false;
      for (const fn of this.listeners.close ?? []) fn({});
    },
    click() { this.clicked = true; return this.disabled ? Promise.resolve() : this.emit('click'); },
    classList:{toggle(name,force) {
      const active = force ?? !classes.has(name);
      if (active) classes.add(name); else classes.delete(name);
      return active;
    }}
  };
}

async function app({storage=new Map(), authenticated=true, detailStatus=200, storageUnavailable=false}={}) {
  const elements = new Map(), requests = [], blobs = [], anchors = [];
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector, element('div'));
    return elements.get(selector);
  };
  get('#filter').value = 'all';
  const galleryTab = element('button'), mineTab = element('button');
  galleryTab.dataset.view = 'gallery'; mineTab.dataset.view = 'mine';
  const form = get('#login-form'), submit = element('button');
  form.elements = {username:{value:'fixture_creator'},password:{value:'fixture-password'}};
  form.querySelector = () => submit;
  form.reset = () => { form.elements.username.value = ''; form.elements.password.value = ''; };
  const context = vm.createContext({
    location:{protocol:'http:'},
    document:{
      querySelector:selector => selector === 'dialog[open]' ? [...elements.values()].find(node=>node.open) ?? null : get(selector),
      querySelectorAll:selector => selector === '[data-view]' ? [galleryTab,mineTab] : [],
      createElement:tag => { const node=element(tag); if (tag==='a') anchors.push(node); return node; },
      createElementNS:(_,tag) => element(tag), createTextNode:text => Object.assign(element('#text'),{textContent:text}),
      visibilityState:'visible'
    },
    sessionStorage:{
      getItem:key => { if(storageUnavailable) throw new Error('Storage unavailable'); return storage.get(key) ?? null; },
      setItem:(key,value) => { if(storageUnavailable) throw new Error('Storage unavailable'); storage.set(key,value); }
    },
    fetch:async (path, options) => {
      requests.push({path,method:options.method});
      let status=200, body;
      if (path === '/api/me') { status=authenticated ? 200 : 401; body=authenticated ? identity : {error:'Please log in.'}; }
      else if (path === '/api/login') { authenticated=true; body=identity; }
      else if (path === '/api/logout') { authenticated=false; body={ok:true}; }
      else if (path === '/api/gallery') body={jobs:[],designs:[],queried_at:'2026-10-12T00:00:00Z'};
      else if (path === '/api/library') body={jobs:fullRecord.jobs,designs:designEntries,queried_at:'2026-10-12T00:00:00Z'};
      else if (path === `/api/jobs/${jobId}/summary`) { status=detailStatus; body=status===200 ? summaryRecord : {error:'Fixture detail request failed.'}; }
      else if (path === `/api/jobs/${jobId}`) body=fullRecord;
      else throw new Error(`Unexpected fixture request: ${path}`);
      return {ok:status>=200 && status<300,status,json:async()=>clone(body)};
    },
    crypto:{randomUUID:()=> 'fixture-save-key'},
    Option:function(text,value) { return Object.assign(element('option'),{textContent:text,value}); },
    Blob, URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:fixture';},revokeObjectURL(){}},
    setInterval:()=>0, setTimeout:()=>0
  });
  vm.runInContext(source, context, {filename:'history/web_assets/app.js'});
  await flush();
  return {context,get,requests,storage,blobs,anchors,form,mineTab,galleryTab};
}

async function verifyNavigation() {
  const storage = new Map();
  let page = await app({storage,authenticated:false});
  assert.equal(page.get('#gallery').children.length,0);
  await page.form.emit('submit',{preventDefault(){},currentTarget:page.form});
  assert.equal(page.get('#gallery').children.length,3);
  assert.equal(page.get('#hero-subtitle').textContent,'MY DESIGNS');
  assert.equal(page.mineTab.attrs['aria-pressed'],'true');

  page = await app({storage});
  assert.equal(page.get('#gallery').children.length,3);
  assert.equal(page.get('#hero-subtitle').textContent,'MY DESIGNS');
  assert.equal(page.requests.at(-1).path,'/api/library');

  await page.galleryTab.click();
  assert.equal(page.get('#gallery').children.length,0);
  assert.equal(page.galleryTab.attrs['aria-pressed'],'true');
  page = await app({storage});
  assert.equal(page.requests.at(-1).path,'/api/gallery');
  assert.equal(page.galleryTab.attrs['aria-pressed'],'true');

  await page.get('#creations-open').click();
  assert.equal(page.get('#gallery').children.length,3);
  await page.get('#logout').click();
  assert.equal(page.get('#identity').hidden,true);
  assert.equal(page.get('#gallery').children.length,0);
  assert.equal(page.galleryTab.attrs['aria-pressed'],'true');
  page = await app({storage,authenticated:false});
  assert.equal(page.requests.at(-1).path,'/api/gallery');
  assert.equal(page.get('#gallery').children.length,0);

  page = await app({storageUnavailable:true});
  assert.equal(page.get('#gallery').children.length,3);
  assert.equal(page.get('#hero-subtitle').textContent,'MY DESIGNS');
}

async function verifyPrivateDetailsAndFullExport() {
  const page = await app();
  for (const card of page.get('#gallery').children) {
    const version = Number(card.attrs['aria-label'].match(/v(\d+)/)[1]);
    await card.click();
    assert.equal(page.requests.at(-1).path,`/api/jobs/${jobId}/summary`);
    assert.equal(page.get('#publish').disabled,false,`Owned design v${version} can be published`);
    assert.equal(page.get('#detail-actions').hidden,false);
    assert.equal(page.get('#export').disabled,false);
    const content = flatten(page.get('#detail-body'));
    assert.ok(content.some(node=>node.tag==='h2' && node.textContent===`Design / v${version}`));
    assert.equal(content.filter(node=>node.tag==='pre').length,0);
    assert.ok(content.some(node=>node.textContent==='Showing the latest 2 of 9 events. EXPORT JSON includes the full record.'));
    page.get('#detail-dialog').close();
  }
  await page.get('#gallery').children[0].click();
  const detailRequests = page.requests.filter(item=>item.path.startsWith(`/api/jobs/${jobId}`));
  assert.ok(detailRequests.every(item=>item.path.endsWith('/summary')));
  await page.get('#export').click();
  assert.deepEqual(page.requests.at(-1),{path:`/api/jobs/${jobId}`,method:'GET'});
  assert.equal(page.blobs.length,1);
  assert.deepEqual(JSON.parse(await page.blobs[0].text()),fullRecord);
  assert.equal(page.anchors.at(-1).download,`c2-${jobId}.json`);
  assert.equal(page.anchors.at(-1).clicked,true);
  assert.equal(page.get('#export').disabled,false);
}

async function verifyLazyRawRecordsAndDetailErrors() {
  const page = await app();
  let serializations = 0;
  const item = {toJSON(){serializations++;return {evidence:'small fixture'};}};
  const section = page.context.rawSection('FIXTURE',[item],()=> 'Open fixture evidence');
  const details = section.children.find(node=>node.tag==='details');
  assert.equal(serializations,0);
  assert.equal(details.children.length,1);
  details.open=true; await details.emit('toggle');
  assert.equal(serializations,1);
  assert.equal(details.children.at(-1).tag,'pre');
  assert.deepEqual(JSON.parse(details.children.at(-1).textContent),{evidence:'small fixture'});
  details.open=false; await details.emit('toggle');
  details.open=true; await details.emit('toggle');
  assert.equal(serializations,1);
  assert.equal(details.children.length,2);

  for (const detailStatus of [403,500]) {
    const failed = await app({detailStatus});
    await failed.get('#gallery').children[0].click();
    assert.equal(failed.get('#publish').disabled,true);
    assert.equal(failed.get('#export').disabled,true);
    assert.equal(failed.get('#detail-notice').textContent,'Fixture detail request failed.');
    assert.equal(failed.get('#detail-dialog').open,true);
  }
}

(async()=>{
  await verifyNavigation();
  await verifyPrivateDetailsAndFullExport();
  await verifyLazyRawRecordsAndDetailErrors();
  console.log('Login/reload view, gallery choice, logout, summary details, v1–v3 publication, lazy JSON, full export and detail errors: OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
