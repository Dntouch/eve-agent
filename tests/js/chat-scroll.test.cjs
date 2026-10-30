const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');
const functions = source.slice(source.indexOf('  function isScrolledToEnd('), source.indexOf('  function ensureBackendUserMessage('));

function client() {
  function element(tag) {
    let top = 0;
    return {
      tag, children: [], textContent: '', clientHeight: 80, height: 200, dataset: {},
      get scrollHeight() { return this.height + this.textContent.length * 10; },
      get scrollTop() { return top; },
      set scrollTop(value) { top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
      append(...nodes) { this.children.push(...nodes); this.height += 100; },
    };
  }
  const chat = element('chat');
  chat.height = 1000;
  chat.clientHeight = 500;
  const frames = new Map();
  let frameId = 0;
  const context = {
    elements: { chatMessages: chat, chatEmpty: {} }, chatScrollFrame: 0,
    document: { createElement: element }, createMessageNode: () => element('article'),
    window: {
      cancelAnimationFrame: id => frames.delete(id),
      requestAnimationFrame: callback => { frames.set(++frameId, callback); return frameId; },
    },
  };
  vm.createContext(context);
  vm.runInContext(functions, context);
  return { chat, context, state: context.liveReasoningState() };
}

test('thinking updates preserve a position above the end, including the first update', () => {
  const { chat, context, state } = client();
  chat.scrollTop = 100;
  context.appendLiveReasoning(state, 'Erster Gedanke.');
  context.appendLiveReasoning(state, ' Weiterer Gedanke.');
  assert.equal(chat.scrollTop, 100);
});

test('thinking follows the end until the user scrolls up, then resumes when they return', () => {
  const { chat, context, state } = client();
  chat.scrollTop = chat.scrollHeight;
  context.appendLiveReasoning(state, 'Erster Gedanke.');
  assert.equal(chat.scrollTop, chat.scrollHeight - chat.clientHeight);
  chat.scrollTop = 50;
  context.appendLiveReasoning(state, ' Weiterer Gedanke.');
  assert.equal(chat.scrollTop, 50);
  chat.scrollTop = chat.scrollHeight;
  context.appendLiveReasoning(state, ' Noch ein Gedanke.');
  assert.equal(chat.scrollTop, chat.scrollHeight - chat.clientHeight);
});

test('reading earlier thinking text does not force the inner panel to the end', () => {
  const { context, state } = client();
  context.appendLiveReasoning(state, 'Langer Gedankengang.');
  state.content.scrollTop = 0;
  context.appendLiveReasoning(state, ' Neue Überlegung.');
  assert.equal(state.content.scrollTop, 0);
});

test('an incoming answer preserves the reader position while a sent message follows the end', () => {
  const { chat, context } = client();
  chat.scrollTop = 100;
  context.appendChatMessage({ role: 'assistant' });
  assert.equal(chat.scrollTop, 100);
  context.appendChatMessage({ role: 'user' });
  assert.equal(chat.scrollTop, chat.scrollHeight - chat.clientHeight);
});
