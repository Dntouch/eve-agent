const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');

function client() {
  function element(tagName) {
    return {
      tagName, children: [], dataset: {}, textContent: '', className: '',
      classList: { add() {} },
      append(...nodes) { this.children.push(...nodes); },
      get childElementCount() { return this.children.length; },
    };
  }
  const c = {
    document: { createElement: element }, messageTime: () => '09:00',
    renderAssistantMarkdown: (node, text) => { node.textContent = text; },
    createActionFeedbackControl: () => null, createDiagnosticCopyControl: () => element('button'),
    elements: { chatMessages: { replaceChildren(...nodes) { this.children = nodes; } }, chatEmpty: {} },
    restorePresentationTurnStatuses() {}, scrollChatToLatest() {},
    createFailureCard: () => element('failure'),
  };
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('  function createMessageNode('),
    source.indexOf('  function createActionFeedbackControl(')), c);
  vm.runInContext(source.slice(source.indexOf('  function renderMessages('),
    source.indexOf('  async function exportConversationPng(')), c);
  return c;
}

test('scheduled request is disclosed under EVE beside tool events with no DU message', () => {
  const c = client();
  const request = 'Suche Neuigkeiten.\nWenn es keine gibt, bleibe stumm. <script>test</script>';
  const execution = { task_id: 'task', name: 'Tesla FSD', request };
  c.renderMessages([
    { role: 'user', content: request, metadata: { input_kind: 'scheduled' } },
    { role: 'assistant', content: 'Neuigkeiten', metadata: { scheduled_execution: execution },
      tool_events: [{ tool: 'web', status: 'completed', summary: 'Gesucht' }] },
  ]);
  const articles = c.elements.chatMessages.children;
  assert.equal(articles.length, 1);
  assert.equal(articles[0].children[0].children[0].textContent, 'EVE');
  const activity = articles[0].children.find(n => n.className === 'message-activity');
  assert.equal(activity.children.length, 2);
  const [task, tools] = activity.children;
  assert.equal(task.tagName, 'details');
  assert.equal(task.open, undefined);
  assert.equal(task.children[0].textContent, 'Geplante Aufgabe');
  assert.equal(task.children[1].textContent, 'Automatisch ausgeführt · Tesla FSD');
  assert.equal(task.children[2].textContent, request);
  assert.equal(tools.className, 'message-tool-events');
});

test('human messages including identical prompts keep their author and text', () => {
  const c = client();
  c.renderMessages([
    { role: 'user', content: 'Prüfe Neuigkeiten' },
    { role: 'user', content: 'Prüfe Neuigkeiten', metadata: {
      conversation_source: { transport: 'chatto', sender_name: 'Stefan' } } },
    { role: 'assistant', content: 'Antwort' },
  ]);
  const articles = c.elements.chatMessages.children;
  assert.equal(articles.length, 3);
  assert.equal(articles[0].children[0].children[0].textContent, 'DU');
  assert.equal(articles[1].children[0].children[0].textContent, 'Stefan');
  assert.equal(articles[0].children[1].textContent, 'Prüfe Neuigkeiten');
  assert.ok(!articles[2].children.some(n => n.className === 'message-activity'));
});

test('scheduled disclosure works without tool events and is also used for export', () => {
  const c = client();
  c.renderMessages([{ role: 'assistant', content: 'Erinnerung', metadata: {
    scheduled_execution: { request: 'Erinnere mich' } } }]);
  const activity = c.elements.chatMessages.children[0].children.find(n => n.className === 'message-activity');
  assert.equal(activity.children.length, 1);
  assert.match(source, /for \(const message of visibleChatMessages\(timeline\)\)/);
});
