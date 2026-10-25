const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname, '../../web');
function cloud() {
  const context = vm.createContext({window: {}});
  vm.runInContext(fs.readFileSync(path.join(web, 'vendor/neurocloud-webgl-v1.js'), 'utf8'), context);
  return context.window.EveNeuroCloud;
}
test('brain dimensions grow with claim count and singleton claims have fog', () => {
  const c = cloud();
  const positions = n => new Map(Array.from({length:n}, (_,i) => [String(i), [i%2 ? -1:1, i%2 ? -1:1, i%2 ? -1:1]]));
  const extent = n => Math.max(...[...c.shapePositions(positions(n), 'brain').values()].map(p=>Math.abs(p[0])));
  assert.ok(extent(800) > extent(100) * 1.9);
  assert.ok(c.buildFogRegions([{id:'one', scope:'private:a'}], new Map([['one',[0,0,0]]])).length > 0);
  const fogRadius = n => c.buildFogRegions(Array.from({length:n},(_,i)=>({id:String(i),scope:'s'})), new Map(Array.from({length:n},(_,i)=>[String(i),[0,0,0]])))[0].radius;
  assert.ok(fogRadius(8000) > fogRadius(1000));
});
test('graph refresh detects changes without a selected turn and retries failed refreshes', async () => {
  let revision='one', loads=0, fail=false;
  const context = vm.createContext({window:{setInterval(){}},document:{hidden:false}, avatarMode:'off',brainwatchOpen:true,brainwatchMode:'memory',memoryExplorerSubview:'cloud',
    memoryExplorerRead:async()=>({revision}),loadAvatarMemoryCloud:async()=>{},setMemoryStructureStatus(){},
    readMemoryStructure:async()=>{loads++;if(fail)throw Error('offline');}});
  const app=fs.readFileSync(path.join(web,'app.js'),'utf8');
  vm.runInContext(app.slice(app.indexOf('  let memoryStructureLoad = null;'), app.indexOf('  async function readMemoryStructure()')),context);
  await vm.runInContext('refreshPersistedMemoryClouds()',context);
  await vm.runInContext('refreshPersistedMemoryClouds()',context);
  assert.equal(loads,1);
  revision='two';fail=true;
  await vm.runInContext('refreshPersistedMemoryClouds()',context);
  fail=false;
  await vm.runInContext('refreshPersistedMemoryClouds()',context);
  assert.equal(loads,3);
});
