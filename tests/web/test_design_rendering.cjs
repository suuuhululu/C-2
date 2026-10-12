// Production SVG/UI functions with a small DOM fixture; no browser or dependencies.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
function node(tag) {
  return {tag,attrs:{},children:[],listeners:{},setAttribute(k,v){this.attrs[k]=String(v)},
    append(...children){this.children.push(...children)},replaceChildren(...children){this.children=children},
    addEventListener(k,fn){this.listeners[k]=fn},showModal(){this.open=true}};
}
const elements = new Map();
const context = vm.createContext({
  document:{createElement:node,createElementNS:(_,tag)=>node(tag)},
  $:key=>{if(!elements.has(key))elements.set(key,node('div'));return elements.get(key)},
  date:()=> 'published date', detailSequence:0,selected:{private:true},
  Option:function(label,value){return Object.assign(node('option'),{textContent:label,value})}
});
const source=fs.readFileSync('history/web_assets/app.js','utf8');
vm.runInContext(source.slice(source.indexOf('function el('),source.indexOf('function date(')),context);
vm.runInContext(source.slice(source.indexOf('function svgNode('),source.indexOf('function paperArt(')),context);
vm.runInContext(source.slice(source.indexOf('function openPublicDetail('),source.indexOf('async function openDetail(')),context);
const flatten=value=>[value,...(value.children||[]).flatMap(flatten)];
for (const angle of [0,90]) {
  const block={brick_type:'1x2x1',color:'red',x:22,y:22,layer:5,orientation_deg:angle};
  const before=JSON.stringify(block),model=context.modelArt([block]);
  const brick=model.children.find(n=>n.tag==='g');
  assert.equal(brick.attrs['data-layer'],'5');
  assert.equal(brick.children.filter(n=>n.tag==='ellipse').length,4); // Two studs, two faces each.
  assert.equal(brick.children[2].attrs.fill,'#db746b');
  const top=brick.children[2].attrs.points.split(' ').map(p=>p.split(',').map(Number));
  const [width,depth]=angle===0?[1,2]:[2,1];
  const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-10);
  close(top[1][0]-top[0][0],-width*Math.sqrt(3)/2);
  close(top[1][1]-top[0][1],width/2);
  close(top[2][0]-top[1][0],depth*Math.sqrt(3)/2);
  close(top[2][1]-top[1][1],depth/2);
  const board=context.board([block],5),rect=board.children.find(n=>n.attrs.fill==='#d76a66');
  assert.equal(rect.attrs.width,String(width));assert.equal(rect.attrs.height,String(depth));
  assert.equal(JSON.stringify(block),before);
}
const blocks=[
  {brick_type:'2x2x1',color:'blue',x:4,y:4,layer:1,orientation_deg:0},
  {brick_type:'1x2x1',color:'red',x:4,y:4,layer:5,orientation_deg:90}
];
const item={design:{design_version:2,blocks},design_version:2,published_at:'2026-10-12',creator:{display_name:'Creator',username:'creator'}};
const before=JSON.stringify(item);context.openPublicDetail(item);
assert.equal(elements.get('#detail-actions').hidden,true);
assert.equal(context.selected,null);
assert.equal(elements.get('#detail-dialog').open,true);
const all=flatten(elements.get('#detail-body')),select=all.find(n=>n.tag==='select');
assert.deepEqual(select.children.map(n=>n.value),['all','1','5']);
select.value='5';select.listeners.change();
const layer=flatten(elements.get('#detail-body')).find(n=>n.attrs['aria-label']==='24×24 assembly board, Layer 5');
assert.ok(layer);
assert.equal(layer.children.filter(n=>['#d76a66','#91b6cf'].includes(n.attrs.fill)).length,1);
assert.ok(layer.children.some(n=>n.attrs.fill==='#d76a66'));
assert.equal(JSON.stringify(item),before);
console.log('Red 1×2 at 0°/90° and Layer 5, published layer selection, private actions hidden, input preserved: OK');
