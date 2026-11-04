const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');

function client({ failAt = -1, refreshFails = false } = {}) {
  const requests = [];
  const retry = { disabled: true }, all = {}, count = {}, close = { focus() {} };
  const list = { append() {} };
  const host = {
    dataset: { total: '85', nextOffset: '40' },
    querySelectorAll(selector) {
      if (selector === '.conversation-learning-select') return cards.map(card => card.input);
      if (selector === 'button, input, textarea') return [retry, all, close, ...cards.map(card => card.input)];
      throw new Error(selector);
    },
    querySelector(selector) {
      return ({ '.conversation-learning-retry-selected': retry, '.conversation-learning-select-all': all,
        '.conversation-learning-result-count': count, '.conversation-learning-job-list': list,
        '.conversation-learning-job': cards[0], 'header button': close })[selector] || null;
    },
  };
  const cards = ['one', 'two', 'three'].map(turnId => ({
    dataset: { turnId }, input: { checked: false },
    querySelector(selector) { return selector === 'textarea' ? { value: 'Prüfnotiz' } : close; },
    remove() { cards.splice(cards.indexOf(this), 1); },
    get nextElementSibling() { return cards[cards.indexOf(this) + 1]; },
    get previousElementSibling() { return cards[cards.indexOf(this) - 1]; },
  }));
  const context = {
    elements: { brainwatchStatisticsWorkspace: { scrollTop: 700 }, brainwatchStatisticsStatus: {} },
    brainwatchCountFormat: new Intl.NumberFormat('de-DE'), auth: {},
    document: { createElement: () => ({}) },
    fetchWithTimeout: async (url, options) => {
      requests.push(JSON.parse(options.body));
      return { ok: requests.length !== failAt, error: 'Speichern fehlgeschlagen' };
    },
    readJsonResponse: async response => response,
    loadBrainwatchStatistics: async () => { if (refreshFails) throw new Error('offline'); },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function updateConversationLearningSelection('),
    source.indexOf('  async function loadConversationLearningResults(')), context);
  return { context, cards, host, retry, all, count, requests };
}

test('selected retries remove only saved entries and adjust the next page offset', async () => {
  const c = client();
  c.cards[0].input.checked = c.cards[2].input.checked = true;
  c.context.updateConversationLearningSelection(c.host);
  assert.equal(c.all.indeterminate, true);
  assert.equal(c.retry.disabled, false);
  const selected = [c.cards[0], c.cards[2]];
  await c.context.changeConversationLearningJobs(c.host, selected, 'retry_turn');
  assert.deepEqual(c.requests, [{ action: 'retry_turn', turn_id: 'one' }, { action: 'retry_turn', turn_id: 'three' }]);
  assert.deepEqual(c.cards.map(card => card.dataset.turnId), ['two']);
  assert.equal(c.host.dataset.nextOffset, '38');
  assert.equal(c.host.dataset.total, '83');
  assert.equal(c.retry.disabled, true);
  assert.equal(c.context.elements.brainwatchStatisticsWorkspace.scrollTop, 700);
});

test('a partial failure keeps failed and unprocessed selections available', async () => {
  const c = client({ failAt: 2 });
  c.cards.forEach(card => { card.input.checked = true; });
  await c.context.changeConversationLearningJobs(c.host, [...c.cards], 'retry_turn');
  assert.deepEqual(c.cards.map(card => card.dataset.turnId), ['two', 'three']);
  assert.equal(c.cards.every(card => card.input.checked && !card.input.disabled), true);
  assert.equal(c.retry.disabled, false);
  assert.equal(c.host.dataset.nextOffset, '39');
  assert.match(c.context.elements.brainwatchStatisticsStatus.textContent, /1 von 3 bearbeitet.*fehlgeschlagen/);
});

test('review submits the note and leaves the list intact when saving fails', async () => {
  const c = client({ failAt: 1 });
  await c.context.changeConversationLearningJobs(c.host, [c.cards[0]], 'review');
  assert.deepEqual(c.requests, [{ action: 'review', turn_id: 'one', note: 'Prüfnotiz' }]);
  assert.equal(c.cards.length, 3);
  assert.equal(c.host.dataset.nextOffset, '40');
  assert.equal(c.host.dataset.busy, 'false');
});

test('a counter refresh failure does not undo a saved review', async () => {
  const c = client({ refreshFails: true });
  await c.context.changeConversationLearningJobs(c.host, [c.cards[0]], 'review');
  assert.equal(c.cards.length, 2);
  assert.equal(c.host.dataset.total, '84');
  assert.match(c.context.elements.brainwatchStatisticsStatus.textContent, /1 von 1 bearbeitet.*Zähler/);
});

test('an in-flight operation cannot be submitted a second time', async () => {
  const c = client();
  c.host.dataset.busy = 'true';
  await c.context.changeConversationLearningJobs(c.host, [c.cards[0]], 'retry_turn');
  assert.equal(c.requests.length, 0);
  assert.equal(c.cards.length, 3);
});
