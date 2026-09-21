const test = require('node:test');
const assert = require('node:assert/strict');
const O = require('../app/web/static/onboarding.js');
const storage = () => {
 const values = new Map();
 return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
};
const example = () => ({data_mode:'replay',target:{symbol:'600519.SH'},condition_logic:'OR',conditions:[
 {type:'PRICE_CHANGE_RATIO',operator:'<=',threshold:-.03},
 {type:'ANNOUNCEMENT_EVENT',event_category:'PERFORMANCE_FORECAST'}
]});

test('opening welcome does not dismiss it; intentional skip survives a reload',()=>{
 const local=storage(), first=O.preferences([()=>local]);
 assert.equal(first.shouldWelcome(),true);
 assert.equal(first.shouldWelcome(),true);
 first.remember('dismissed');
 assert.equal(O.preferences([()=>local]).shouldWelcome(),false);
});
test('starting and finishing the example persist without any task or identity data',()=>{
 const local=storage(),pref=O.preferences([()=>local]);
 for(const status of ['started','completed']){
  pref.remember(status);
  assert.deepEqual(JSON.parse(local.getItem(O.KEY)),{status});
  assert.equal(O.preferences([()=>local]).shouldWelcome(),false);
 }
});
test('blocked local storage falls back to session storage; both blocked still work',()=>{
 const blocked=()=>{throw new Error('SecurityError');},session=storage();
 const pref=O.preferences([blocked,()=>session]);
 pref.remember('dismissed');
 assert.equal(O.preferences([blocked,()=>session]).shouldWelcome(),false);
 const memory=O.preferences([blocked,blocked]);
 assert.equal(memory.shouldWelcome(),true);
 assert.doesNotThrow(()=>memory.remember('started'));
 assert.equal(memory.shouldWelcome(),false);
});
test('corrupt or unknown saved values do not break first use',()=>{
 const local=storage();
 for(const invalid of ['{','null','{"status":"unexpected"}']){
  local.setItem(O.KEY,invalid);
  assert.equal(O.preferences([()=>local]).shouldWelcome(),true);
 }
});
test('tutorial cannot simulate real data or a changed company, threshold, or logical relation',()=>{
 assert.equal(O.isExample(example()),true);
 for(const patch of [{data_mode:'live'},{target:{symbol:'300750.SZ'}},{condition_logic:'AND'},{conditions:[]}]){
  assert.equal(O.isExample({...example(),...patch}),false);
 }
 for(const patch of [{operator:'<'},{threshold:-.04},{type:'PRICE'}]){
  const spec=example();Object.assign(spec.conditions[0],patch);assert.equal(O.isExample(spec),false);
 }
});
test('only the corresponding simulated condition notification can complete the tutorial',()=>{
 const good={task_id:'example',mode:'replay',kind:'condition'};
 assert.equal(O.exampleAlert([], 'example'),null);
 for(const patch of [{task_id:'other'},{mode:'live'},{kind:'health'},{kind:'recovery'}]){
  assert.equal(O.exampleAlert([{...good,...patch}],'example'),null);
 }
 assert.equal(O.exampleAlert([good],'example'),good);
});
