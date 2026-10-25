const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const renderer = source.slice(source.indexOf('  function createActionFeedbackControl('),
  source.indexOf('  function scrollChatToLatest('));
const document = { createElement(tag) {
  return { tag, dataset: {}, children: [], textContent: '', handlers: {}, value: '',
    append(...children) { this.children.push(...children); }, replaceChildren(...children) { this.children = children; },
    setAttribute() {}, focus() {}, addEventListener(kind, handler) { this.handlers[kind] = handler; },
    querySelectorAll(tag) { return this.children.flatMap(c => [...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag)]); } };
} };
const requests = [];
let posted;
const fetch = async (url, options) => { posted = JSON.parse(options.body); requests.push({url, ...posted}); return {ok: true}; };
const json = async () => ({feedback: {decision: posted.decision === 'undo' ? null : posted.decision, explanation: posted.explanation}});
const render = new Function('document', 'fetchWithTimeout', 'readJsonResponse', 'auth', 'window',
  `${renderer}; return createActionFeedbackControl;`)(document, fetch, json, {}, {requestAnimationFrame(fn) { fn(); }});
const wait = () => new Promise(setImmediate);
const click = async (control, label) => {
  const button = control.querySelectorAll('button').find(n => n.textContent === label);
  assert.ok(button, `Missing ${label}`); button.handlers.click(); await wait();
};
(async () => {
  const message = {role: 'assistant', id: 'answer', conversation_id: 'chat', metadata: {route: 'web'}};
  let control = render(message);
  assert.ok(control, 'Ordinary answers must be rateable without semantic claim IDs');
  await click(control, '👎');
  assert.equal(requests[0].url, '/api/conversations/chat/messages/answer/feedback');
  assert.equal(requests[0].decision, 'incorrect');
  assert.equal(message.metadata.answer_feedback.decision, 'incorrect');
  control = render(message); // Simulate a redraw after loading persisted metadata.
  assert.equal(control.dataset.feedbackState, 'incorrect');
  await click(control, 'Erklären');
  const input = control.querySelectorAll('textarea')[0];
  assert.equal(input.maxLength, undefined, 'No new hard explanation cap for ordinary ratings');
  input.value = 'Das war nicht meine Frage.';
  control.querySelectorAll('form')[0].handlers.submit({preventDefault() {}}); await wait();
  assert.equal(message.metadata.answer_feedback.explanation, input.value);
  await click(control, 'Rückgängig');
  assert.equal(message.metadata.answer_feedback, null);
  await click(control, '👍');
  assert.equal(message.metadata.answer_feedback.decision, 'correct');
  assert.equal(render({role: 'user', id: 'u', conversation_id: 'chat'}), null);
  assert.equal(render({role: 'assistant', conversation_id: 'chat'}), null);
  const legacy = render({role:'assistant',id:'old',conversation_id:'chat',metadata:{turn_state:'operational_resolved',
    turn_state_details:{operational_execution:true,semantic_link_id:'claim'}}});
  const count=requests.length; await click(legacy,'👎');
  assert.equal(requests.length,count,'Legacy action feedback must retain its original explanation flow');
  assert.equal(legacy.querySelectorAll('textarea').length,1);
  console.log('Answer feedback: plain answers, negative vote, optional correction, redraw, undo and legacy controls passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
