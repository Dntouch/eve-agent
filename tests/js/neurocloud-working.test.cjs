const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const timers = new Set();
  const context = vm.createContext({window: {}, Date,
    setInterval(fn) { timers.add(fn); return fn; },
    clearInterval(fn) { timers.delete(fn); }});
  for (const name of ['vendor/neurocloud-webgl-v1.js', 'neurocloud-working.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../web', name), 'utf8'), context);
  }
  return {layer: context.window.EveWorkingMemoryCloud, cloud: context.window.EveNeuroCloud, timers};
}

test('working positions preserve durable positions and remain stable as material changes', () => {
  const {cloud} = load();
  const base = new Map([['claim:a', [1, 2, 3]]]);
  const node = {id: 'work:a', workspace_id: 'one', node_kind: 'working_material'};
  const first = cloud.layoutWorkingMemory(base, [node]);
  const next = cloud.layoutWorkingMemory(base, [node, {...node, id: 'work:b'}]);
  assert.deepEqual([...first.get('claim:a')], [1, 2, 3]);
  assert.deepEqual([...first.get('work:a')], [...next.get('work:a')]);
  assert.equal(base.has('work:a'), false);
  assert.ok(first.get('work:a')[1] > 7);
});

test('only fresh new recorded accesses pulse; initial load, repeats and old events do not', async () => {
  const {layer} = load();
  const now = new Date().toISOString();
  const a = {id: 'call-a:returned', occurred_at: now};
  let snapshot = {version: 'working-memory-graph-v1', events: [a], nodes: [], edges: []};
  const renders = [];
  const controller = new layer.WorkingMemoryLayer({read: async () => snapshot,
    render: (data, impulses) => renders.push(impulses.map(event => event.id)), status() {}, active: () => true});
  await controller.poll();
  await controller.poll();
  snapshot = {...snapshot, events: [a, {id: 'new', occurred_at: now}, {id: 'old', occurred_at: '2000-01-01'}]};
  await controller.poll();
  await controller.poll();
  assert.deepEqual(renders.map(ids => [...ids]), [[], [], ['new'], []]);
});

test('hidden views do not poll and stopped in-flight requests cannot redraw', async () => {
  const {layer, timers} = load();
  let active = false, reads = 0, renders = 0, resolve;
  const controller = new layer.WorkingMemoryLayer({read: () => {
    reads++; return new Promise(done => { resolve = done; });
  }, render: () => renders++, status() {}, active: () => active});
  controller.sync();
  assert.equal(reads, 0);
  assert.equal(timers.size, 0);
  active = true;
  const pending = controller.poll();
  await controller.poll();
  assert.equal(reads, 1);
  controller.stop();
  resolve({version: 'working-memory-graph-v1', events: []});
  await pending;
  assert.equal(renders, 0);
});

test('poll failure reports stale view without inventing activity', async () => {
  const {layer} = load();
  let status = '', renders = 0;
  const controller = new layer.WorkingMemoryLayer({read: async () => {throw Error('offline');},
    render: () => renders++, status: value => {status = value;}, active: () => true});
  await controller.poll();
  assert.match(status, /veraltet/);
  assert.equal(renders, 0);
});
