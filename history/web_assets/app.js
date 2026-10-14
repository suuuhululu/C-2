'use strict';
const $ = (selector) => document.querySelector(selector);
const isFilePreview = location.protocol === 'file:';
const viewStorageKey = 'c2-history-view';
let user = null, library = {jobs: [], designs: []}, view = 'gallery', selected = null;
let detailSequence = 0, librarySequence = 0, saveKey = null, selectedVersion = null;
const events = {JOB_STARTED:'Job started', PLAN_ADOPTED:'Design and plan adopted', CURRENT_ADOPTED:'Current state adopted', CHECK_RESULT:'Assembly check', PLAN_WORK_EXHAUSTED:'Plan work exhausted', ASSEMBLY_COMPLETED:'Assembly completion recorded', JOB_COMPLETED:'Job completion recorded', INTENT_RECEIVED:'Intent received', DELIVERY_RESULT:'Delivery result', STEP_CONFIRMED:'Step confirmed'};
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function date(value) { return value ? new Date(value).toLocaleString('en-GB', {timeZone:'Asia/Seoul', hour12:false}) : 'No record'; }
function complete(job) { return job.result === 'COMPLETE'; }
async function api(path, data) {
  if (isFilePreview) throw new Error('Open the local app to access your records.');
  const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', credentials:'same-origin', headers: data === undefined ? {} : {'Content-Type':'application/json'}, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/login' && user) void signedOut();
    const error = new Error(result.error || 'Request failed.');
    error.status = response.status;
    throw error;
  }
  return result;
}
function notice(message, error = false) { $('#notice').textContent = message; $('#notice').classList.toggle('error', error); }
function updateView() {
  document.querySelectorAll('[data-view]').forEach(button=>{
    const active = button.dataset.view === view;
    button.classList.toggle('active',active); button.setAttribute('aria-pressed',String(active));
  });
  $('#filter').hidden = view === 'gallery';
  $('#hero-subtitle').textContent = view === 'mine' ? 'MY DESIGNS' : '#C–2';
  $('.collection').setAttribute('aria-label', view === 'mine' ? 'My assembly designs' : 'Published assembly designs');
  try { sessionStorage.setItem(viewStorageKey, view); } catch (_) { /* View preferences are optional. */ }
}
async function signedOut() {
  user = null; library = {jobs:[], designs:[]}; selected = null; view = 'gallery';
  librarySequence++; detailSequence++;
  $('#identity').hidden = true; $('#identity').textContent = '';
  $('#login-open').hidden = false; $('#logout').hidden = true;
  $('#detail-dialog').close(); $('#detail-body').replaceChildren();
  $('#search').value = ''; $('#filter').value = 'all'; updateView(); render();
  await refresh();
}
async function signedIn(identity, manage = false) {
  user = identity; $('#identity').textContent = identity.username; $('#identity').hidden = false;
  $('#login-open').hidden = true; $('#logout').hidden = false;
  let savedView = null;
  try { savedView = sessionStorage.getItem(viewStorageKey); } catch (_) { /* View preferences are optional. */ }
  view = manage || savedView !== 'gallery' ? 'mine' : 'gallery';
  updateView(); await refresh();
}
async function chooseView(next) {
  if (next === 'mine' && !user) { showLogin(); return; }
  view = next; library = {jobs:[],designs:[]}; $('#filter').value = 'all';
  $('#detail-dialog').close(); updateView(); render(); await refresh();
}
async function refresh() {
  if (isFilePreview) { showLogin(); return; }
  if (view === 'mine' && !user) { showLogin(); return; }
  const sequence = ++librarySequence;
  $('#refresh').disabled = true; notice('Loading designs.');
  if (!library.designs.length) {
    $('#welcome').hidden = true; $('#empty').hidden = false;
    $('#empty h2').textContent = 'Loading designs…';
    $('#empty p').textContent = 'Reading your records. Please wait.';
  }
  try {
    const result = await api(view === 'gallery' ? '/api/gallery' : '/api/library');
    if (sequence !== librarySequence) return;
    library = result; render();
    notice(view === 'gallery' ? `${library.designs.length} published designs · open to all visitors` : `${library.designs.length} designs · choose what to publish`);
    $('#updated').textContent = `UPDATED ${date(library.queried_at)}`;
  } catch (error) {
    if (sequence === librarySequence) {
      notice(error.message, true);
      if (!library.designs.length) {
        $('#empty h2').textContent = 'Could not load designs.';
        $('#empty p').textContent = error.message;
      }
    }
  }
  finally { $('#refresh').disabled = false; }
}
function svgNode(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}
function board(blocks, layer = null) {
  const svg = svgNode('svg', {viewBox:'-2 -2 28 28', class:'board', role:'img', 'aria-label':`24×24 assembly board${layer ? `, Layer ${layer}` : ', top layer at each position'}`});
  svg.append(svgNode('rect', {x:0,y:0,width:24,height:24,fill:'#f6f6f0',stroke:'#a5a59e','stroke-width':.1}));
  for (let i = 0; i <= 24; i++) {
    svg.append(svgNode('path', {d:`M ${i} 0 V 24 M 0 ${i} H 24`,stroke:'#d9d9d1','stroke-width':.035}));
  }
  // Ascending layers make the overview show the top block at overlapping positions.
  for (const block of [...blocks].filter(b => layer === null || b.layer === layer).sort((a,b) => a.layer-b.layer)) {
    const parts = block.brick_type.split('x').map(Number);
    const [w,h] = block.orientation_deg % 180 === 0 ? parts : [parts[1],parts[0]];
    const color = {yellow:'#edca35',blue:'#91b6cf',red:'#d76a66'}[block.color];
    svg.append(svgNode('rect', {x:block.x,y:block.y,width:w,height:h,fill:color,stroke:'#4b4b44','stroke-width':.12}));
    for(let x=0;x<w;x++) for(let y=0;y<h;y++) svg.append(svgNode('circle', {cx:block.x+x+.5,cy:block.y+y+.5,r:.25,fill:'none',stroke:'#4b4b4470','stroke-width':.07}));
  }
  for (const [text,x,y] of [['0',-.8,-.3],['x →',20,-.7],['y ↓',-1.5,12]]) {
    const label=svgNode('text',{x,y,'font-size':.8,fill:'#888'});label.textContent=text;svg.append(label);
  }
  return svg;
}
function modelArt(blocks) {
  const svg = svgNode('svg', {class:'assembly-model',role:'img','aria-label':'3D target design model'});
  if (!blocks.length) {
    svg.setAttribute('viewBox','0 0 220 120');
    const text = svgNode('text',{x:110,y:60,'text-anchor':'middle','font-size':10,fill:'#999'});
    text.textContent = 'NO BLOCKS'; svg.append(text); return svg;
  }
  // Match the HMI's LDraw display proportions: body 24/20, stud height 4/20.
  // This projection never supplies physical Robot coordinates or completion evidence.
  const project = (x,y,z) => [(y-x)*Math.sqrt(3)/2,(x+y)*.5-z*1.2];
  const size = block => {
    const [w,d] = block.brick_type.split('x').map(Number);
    return block.orientation_deg === 90 ? [d,w] : [w,d];
  };
  const points = [];
  const polygon = (vertices, fill, parent = svg) => {
    const projected = vertices.map(point=>project(...point)); points.push(...projected);
    parent.append(svgNode('polygon',{points:projected.map(point=>point.join(',')).join(' '),fill,stroke:'#344453','stroke-width':.035,'stroke-linejoin':'round'}));
  };
  const minX = Math.min(...blocks.map(b=>b.x))-1, minY = Math.min(...blocks.map(b=>b.y))-1;
  const maxX = Math.max(...blocks.map(b=>b.x+size(b)[0]))+1, maxY = Math.max(...blocks.map(b=>b.y+size(b)[1]))+1;
  polygon([[minX,minY,0],[maxX,minY,0],[maxX,maxY,0],[minX,maxY,0]],'#f4f4f0');
  // Draw each layer from far to near, then draw higher layers over hidden studs.
  for (const block of [...blocks].sort((a,b)=>a.layer-b.layer || a.x+a.y-b.x-b.y)) {
    const {x,y,layer:z} = block, [w,d] = size(block);
    const [top,left,right] = {yellow:['#efc94b','#d3b242','#b89b3a'],blue:['#699bde','#5d89c4','#5177ab'],red:['#db746b','#bd625d','#a44f4c']}[block.color];
    const brick = svgNode('g',{'data-layer':z}); svg.append(brick);
    polygon([[x,y+d,z],[x+w,y+d,z],[x+w,y+d,z-1],[x,y+d,z-1]],left,brick);
    polygon([[x+w,y,z],[x+w,y+d,z],[x+w,y+d,z-1],[x+w,y,z-1]],right,brick);
    polygon([[x,y,z],[x+w,y,z],[x+w,y+d,z],[x,y+d,z]],top,brick);
    for (let dx=0;dx<w;dx++) for (let dy=0;dy<d;dy++) {
      const [cx,cy] = project(x+dx+.5,y+dy+.5,z+1/6);
      points.push([cx-.37,cy-.22],[cx+.37,cy+.22]);
      brick.append(svgNode('ellipse',{cx,cy:cy+.2,rx:.367,ry:.212,fill:left,stroke:'#526170','stroke-width':.025}));
      brick.append(svgNode('path',{d:`M${cx-.367} ${cy+.2} v-.2 M${cx+.367} ${cy+.2} v-.2`,stroke:'#526170','stroke-width':.025}));
      brick.append(svgNode('ellipse',{cx,cy,rx:.367,ry:.212,fill:top,stroke:'#526170','stroke-width':.025}));
    }
  }
  const xs = points.map(p=>p[0]), ys = points.map(p=>p[1]);
  const left = Math.min(...xs)-.6, top = Math.min(...ys)-.6;
  svg.setAttribute('viewBox',`${left} ${top} ${Math.max(...xs)-left+.6} ${Math.max(...ys)-top+.6}`);
  return svg;
}
function paperArt(letter, tall, blocks = null) {
  const height = tall ? 395 : 250, corner = height - 75;
  const svg = svgNode('svg', {viewBox:`0 0 292 ${height+42}`,class:'paper-art','aria-hidden':'true'});
  for (const offset of [40,20]) svg.append(svgNode('rect',{x:offset+1,y:offset+1,width:248,height:height-1,fill:'#fff',stroke:'#777','stroke-width':.8}));
  svg.append(svgNode('path',{d:`M1 1 H249 V${corner} L174 ${height} H1 Z`,fill:'#fff',stroke:'#777','stroke-width':.8}));
  svg.append(svgNode('path',{d:`M174 ${height} V${corner} H249`,fill:'none',stroke:'#aaa','stroke-width':.8}));
  if (blocks !== null) {
    const label = svgNode('text',{x:18,y:27,fill:'#888','font-family':'Arial,sans-serif','font-size':9,'letter-spacing':1});
    label.textContent = 'TARGET MODEL'; svg.append(label);
    const model = modelArt(blocks);
    for (const [key,value] of Object.entries({x:15,y:44,width:220,height:height-130})) model.setAttribute(key,value);
    svg.append(model);
  } else {
    const text = svgNode('text',{x:24,y:142,fill:'#262626','font-family':'Times New Roman,serif','font-style':'italic','font-size':176});
    text.textContent=letter;svg.append(text);
  }
  return svg;
}
function render() {
  $('#public-count').textContent = view === 'gallery' ? library.designs.length : '—';
  $('#design-count').textContent = view === 'mine' ? library.designs.length : '—';
  $('#welcome').hidden = true; $('#gallery').replaceChildren(); $('#empty').hidden = true;
  const query = $('#search').value.trim().toLowerCase(), filter = view === 'gallery' ? 'all' : $('#filter').value;
  const items = library.designs.slice().reverse().filter(item => {
    const text = `${item.creator.display_name} ${item.creator.username} ${item.job_id} v${item.design_version}`.toLowerCase();
    return text.includes(query) && (filter === 'all' || (filter === 'published' ? item.published : !item.published));
  });
  items.forEach((item,index) => {
    const button = el('button', undefined, `paper model-paper${index % 3 === 1 ? ' short' : ''}`);
    button.append(paperArt(index % 3 === 1 ? 'C' : 'A', index % 3 !== 1,item.design.blocks));
    const caption = el('span', `Design v${item.design_version} · BY @${item.creator.username}${view === 'mine' ? ` · ${item.published ? 'Published' : 'Not published'}` : ''}`, 'paper-caption');
    button.append(caption);
    button.setAttribute('aria-label', `Design v${item.design_version} by ${item.creator.username} — view design`);
    button.addEventListener('click', () => view === 'gallery' ? openPublicDetail(item) : openDetail(item.job_id,item.design_version));
    $('#gallery').append(button);
  });
  $('#empty').hidden = items.length > 0;
  $('#empty h2').textContent = query || filter !== 'all' ? 'No matching designs.' : view === 'gallery' ? 'No published designs yet.' : 'No designs linked to your account yet.';
  $('#empty p').textContent = view === 'gallery' ? 'Creators choose which design versions to share here.' : 'Imported designs linked to your creator account appear here. New designs start unpublished.';
}
function openPublicDetail(item) {
  detailSequence++; selected = null;
  $('#detail-actions').hidden = true; $('#publication-status').textContent = ''; $('#detail-notice').textContent = '';
  $('#detail-label').textContent = 'PUBLISHED DESIGN';
  const visual = el('div',undefined,'public-model'); visual.append(modelArt(item.design.blocks));
  const drawing = el('div'); drawing.append(board(item.design.blocks));
  const picker = el('label','DESIGN VIEW ','layer-picker'), select = el('select');
  select.setAttribute('aria-label','Select published design layer');
  select.append(new Option('Overview · top layer','all'));
  [...new Set(item.design.blocks.map(b=>b.layer))].sort((a,b)=>a-b).forEach(layer=>select.append(new Option(`Layer ${layer}`,String(layer))));
  select.addEventListener('change',()=>drawing.replaceChildren(board(item.design.blocks,select.value==='all' ? null : Number(select.value))));
  picker.append(select);
  const blueprint = el('div'); blueprint.append(picker,drawing); visual.append(blueprint);
  const grid = el('div',undefined,'detail-grid public-design-grid');
  grid.append(visual,facts([['Creator',`${item.creator.display_name} (@${item.creator.username})`],['Design version',`v${item.design_version}`],['Published',date(item.published_at)],['Blocks',String(item.design.blocks.length)]]));
  $('#detail-body').replaceChildren(el('h2',`Design / v${item.design_version}`),grid,el('p','This model shows the adopted design target. Publication is separate from assembly completion.'));
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
}
function facts(items) {
  const list = el('dl', undefined, 'facts');
  for (const [key,value] of items) { const row=el('div');row.append(el('dt',key),el('dd',value));list.append(row); }
  return list;
}
function rawSection(title, items, label) {
  const section = el('section', undefined, 'record-section'); section.append(el('h3', `${title} / ${items.length}`));
  if (!items.length) section.append(el('p','No record'));
  items.forEach((item,index) => {
    const details=el('details'); details.append(el('summary',label(item,index)));
    details.addEventListener('toggle',()=>{
      if (details.open && details.children.length === 1) details.append(el('pre',JSON.stringify(item,null,2)));
    });
    section.append(details);
  });
  return section;
}
async function openDetail(jobId, version = null) {
  const sequence = ++detailSequence; selected = null; selectedVersion = version; saveKey = crypto.randomUUID();
  $('#detail-actions').hidden = false; $('#publish').disabled = true; $('#publication-status').textContent = '';
  $('#detail-body').replaceChildren(el('p','Loading record.')); $('#detail-notice').textContent='';
  $('#export').disabled=true; $('#save').disabled=true;
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const result = await api(`/api/jobs/${jobId}/summary`);
    if (sequence !== detailSequence || !$('#detail-dialog').open) return;
    selected = result; renderDetail(version); $('#export').disabled=false;
  } catch(error) { if (sequence === detailSequence) $('#detail-notice').textContent=error.message; }
}
function renderDetail(version) {
  const body=$('#detail-body'), job=selected.jobs[0], designs=selected.designs;
  const design=designs.find(d => d.design_version === (version ?? selectedVersion)) ?? designs.at(-1);
  selectedVersion = design ? design.design_version : null;
  const item = library.designs.find(d=>d.job_id === job.job_id && d.design_version === selectedVersion);
  $('#publish').disabled = !item;
  $('#publish').textContent = item && item.published ? 'UNPUBLISH DESIGN' : 'PUBLISH DESIGN ↗';
  $('#publication-status').textContent = item && item.published ? 'Published in the public gallery.' : 'Not published. Only you can manage this design.';
  $('#detail-label').textContent=`ASSEMBLY RECORD / ${job.job_id.slice(0,8).toUpperCase()}`;
  const heading=el('div',undefined,'detail-heading');heading.append(el('h2',design ? `Design / v${design.design_version}` : 'Assembly record'),el('span',job.job_id,'job-id'));
  body.replaceChildren(heading);
  const grid=el('div',undefined,'detail-grid'), visual=el('div');
  if(design) {
    const drawing=el('div');drawing.append(board(design.design.blocks));
    const picker=el('label','VIEW ','layer-picker'), select=el('select');select.setAttribute('aria-label','Select design layer');
    select.append(new Option('Overview · top layer','all'));
    [...new Set(design.design.blocks.map(b=>b.layer))].sort().forEach(layer=>select.append(new Option(`Layer ${layer}`,layer)));
    select.addEventListener('change',()=>drawing.replaceChildren(board(design.design.blocks,select.value === 'all' ? null : Number(select.value))));
    picker.append(select);visual.append(drawing,picker);
    const legend=el('div',undefined,'legend');for(const [color,name] of [['yellow','Yellow'],['blue','Blue'],['red','Red']]){const part=el('span');part.append(el('i',undefined,color),document.createTextNode(name));legend.append(part);}visual.append(legend);
  } else visual.append(el('p','No adopted design recorded'));
  grid.append(visual,facts([['Assembly completion',complete(job) ? 'Evidence recorded' : 'No evidence recorded'],['Plan work exhausted',selected.completion.work_exhaustion === 'RECORDED' ? 'Recorded' : 'No final MVP record'],['DB snapshot confirmation',selected.storage.status === 'SAVED' ? 'Current snapshot confirmed' : 'Current snapshot unconfirmed'],['Imported events',`${selected.timeline_total ?? selected.timeline.length}`],['Job started',date(job.started_at)],['Last record',date(job.last_seen_at)]]));body.append(grid);
  body.append(el('p','These are imported DB records. Completion evidence refers to the final adopted design. Snapshot confirmation acknowledges the currently imported events; it does not confirm assembly completion.'));
  body.append(rawSection('ADOPTED DESIGNS',selected.designs,item=>`v${item.design_version} · ${date(item.adopted_at)}`));
  body.append(rawSection('PLANS',selected.plans,item=>`${item.plan_id} · ${item.is_last_adopted ? 'Last adopted' : 'Previously adopted'}`));
  body.append(rawSection('CURRENT STATES',selected.currents,item=>`revision ${item.current_revision} · ${item.kind}`));
  body.append(rawSection('CHECKS',selected.checks,item=>`${item.response.check_kind} / ${item.response.status} / ${item.response.comparison ?? 'No comparison'} · ${item.disposition}`));
  body.append(rawSection('INTENT RESPONSES',selected.hri,item=>`request ${item.request_id}`));
  if (selected.timeline_total > selected.timeline.length) body.append(el('p',`Showing the latest ${selected.timeline.length} of ${selected.timeline_total} events. EXPORT JSON includes the full record.`));
  body.append(rawSection('TIMELINE',selected.timeline,item=>`${date(item.occurred_at)} · ${events[item.event] ?? item.event}${item.reason ? ` / ${item.reason}` : ''}`));
  $('#save').disabled=selected.storage.status === 'SAVED';
  $('#save').textContent=selected.storage.status === 'SAVED' ? 'DB SNAPSHOT CONFIRMED' : 'CONFIRM DB SNAPSHOT ↗';
}
function showLogin() {
  if (isFilePreview) { if (!$('#preview-dialog').open) $('#preview-dialog').showModal(); return; }
  $('#login-error').textContent=''; if(!$('#login-dialog').open) $('#login-dialog').showModal(); }
['#welcome-login','#welcome-history','#welcome-record'].forEach((id,index)=>$(id).append(paperArt(index===1?'C':'A',index!==1)));
$('#collection-open').addEventListener('click',()=>$('#collection-dialog').showModal());
$('#creations-open').addEventListener('click',()=>chooseView('mine'));
['#login-open','#welcome-login','#welcome-history','#welcome-record'].forEach(id=>$(id).addEventListener('click',showLogin));
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$('#'+button.dataset.close).close()));
$('#detail-dialog').addEventListener('close',()=>{ detailSequence++; selected=null; });
$('#about-open').addEventListener('click',()=>$('#about-dialog').showModal());
$('#refresh').addEventListener('click',refresh); $('#search').addEventListener('input',render); $('#filter').addEventListener('change',render);
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>chooseView(button.dataset.view)));
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault(); const form=event.currentTarget, button=form.querySelector('[type=submit]');button.disabled=true;$('#login-error').textContent='';
  try {const identity=await api('/api/login',{username:form.elements.username.value,password:form.elements.password.value});form.reset();$('#login-dialog').close();await signedIn(identity,true);}
  catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}
});
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});await signedOut();}catch(error){notice(error.message,true);}});
$('#export').addEventListener('click',async()=>{
  if (!selected) return;
  const jobId=selected.owner.job_id, sequence=detailSequence; $('#export').disabled=true;
  try {
    const result=await api(`/api/jobs/${jobId}`);
    if (sequence !== detailSequence || !selected) return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),link=el('a');
    link.href=url;link.download=`c2-${jobId}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) { if (sequence === detailSequence) $('#detail-notice').textContent=error.message; }
  finally { if (sequence === detailSequence && selected) $('#export').disabled=false; }
});
$('#save').addEventListener('click',async()=>{
  if(!selected)return;const jobId=selected.owner.job_id, sequence=detailSequence;$('#save').disabled=true;
  try{await api(`/api/jobs/${jobId}/save`,{save_key:saveKey});const result=await api(`/api/jobs/${jobId}/summary`);if(sequence!==detailSequence||!selected)return;selected=result;renderDetail(null);$('#detail-notice').textContent='Confirmation of the current DB event snapshot has been recorded.';}
  catch(error){if(sequence===detailSequence){$('#detail-notice').textContent=error.message;$('#save').disabled=false;}}
});
$('#publish').addEventListener('click',async()=>{
  if (!selected || selectedVersion === null) return;
  const jobId = selected.owner.job_id, version = selectedVersion, sequence = detailSequence;
  const item = library.designs.find(d=>d.job_id === jobId && d.design_version === version);
  if (!item) return;
  $('#publish').disabled = true;
  try {
    const result = await api(`/api/designs/${jobId}/${version}/publication`,{published:!item.published});
    item.published = result.published;
    if (sequence === detailSequence && selected) {
      renderDetail(version);
      $('#detail-notice').textContent = result.published ? 'This design version is now visible in the public gallery.' : 'This design version has been removed from the public gallery.';
    }
    await refresh();
  } catch(error) {
    if (sequence === detailSequence) { $('#detail-notice').textContent = error.message; $('#publish').disabled = false; }
  }
});
(async()=>{
  if (isFilePreview) {
    $('#updated').textContent = 'FILE PREVIEW'; $('#server-link').hidden = false;
    notice('File preview. Open the local app to explore published designs.'); return;
  }
  try { const identity = await api('/api/me'); await signedIn(identity); }
  catch(error) { if (error.status === 401) await refresh(); else notice(error.message,true); }
})();
setInterval(()=>{
  if (!isFilePreview && document.visibilityState === 'visible' && !$('#refresh').disabled && !document.querySelector('dialog[open]')) void refresh();
},15000);
