// Execute the real card renderer with a minimal DOM; listeners are not invoked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const renderer = source.slice(source.indexOf('  function createFailureCard('),
  source.indexOf('  async function recoverStoredAnswer('));
const document = { createElement(tag) {
  return { tag, dataset: {}, children: [], textContent: '', append(...children) { this.children.push(...children); },
    listeners: {}, setAttribute() {}, addEventListener(type, handler) { this.listeners[type] = handler; } };
} };
const render = new Function('document', `${renderer}; return createFailureCard;`)(document);
const reason = 'Vom lokalen Modell kam keine verwertbare Antwort. Der genaue Servergrund wurde nicht gemeldet.';
const report = { reason, category: 'empty_model_response', execution_observation: {
  repeated_material_selections: 42, fresh_contexts: 29, checkpoint_missing: true, task_progress_assessed: false
} };
const card = render(report);
assert.equal(card.children[1].textContent, reason);
assert.match(card.children[2].textContent, /42 wiederholte Abrufversuche/);
assert.match(card.children[2].textContent, /29 Wechsel/);
assert.match(card.children[2].textContent, /keine gesicherte Erklärung/);
assert.equal(card.children.filter(node => node.tag === 'p').length, 2);
assert.equal(render({reason}).children.filter(node => node.tag === 'p').length, 1);
assert.equal(render({reason, execution_observation: {checkpoint_missing: false}}).children.filter(node => node.tag === 'p').length, 1);
console.log('Failure card: observed activity remains separate from the unknown model failure cause.');

(async () => {
  const submitted = [];
  const renderResume = new Function('document', 'requestBusy', 'activeConversationId',
    'submitMessage', 'setDetail', `${renderer}; return createFailureCard;`)(
      document, false, 'chat', async value => submitted.push(value), message => { throw Error(message); });
  const card = renderResume({reason, input_text:'Originalauftrag', conversation_id:'chat',
    turn_id:'failed', working_memory:{workspace_id:'workspace'}});
  const resume = card.children.find(node => node.tag === 'button' && node.textContent === 'Fortsetzen');
  assert.ok(resume);
  await resume.listeners.click();
  assert.equal(submitted.length, 1);
  assert.deepEqual(submitted[0].retryContext, {source_turn_id:'failed', correction:''});
  assert.equal(submitted[0].text, 'Originalauftrag');
  assert.equal(resume.disabled, false);
  console.log('Failure card: continuation keeps the source attempt and permits an empty correction.');
})().catch(error => { console.error(error); process.exitCode = 1; });
