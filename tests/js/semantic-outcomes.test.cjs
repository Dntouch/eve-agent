const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');

function render(items) {
  const element = tag => ({ tag, children: [], append(...nodes) { this.children.push(...nodes); } });
  const context = { document: { createElement: element } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function renderSemanticOutcomes('),
    source.indexOf('  async function loadSemanticLearning(')), context);
  return context.renderSemanticOutcomes({ recent_learning: items });
}

test('shows candidates, failures, skipped learning and partial success separately', () => {
  const panel = render([
    { kind: 'semantic_candidate', utterance: 'Kerzenromantik', reason: 'goal_unverified' },
    { kind: 'rejected', utterance: 'Rollo', reason: 'missing reference' },
    { kind: 'not_reusable', utterance: 'Einmaliger Auftrag', reason: 'Model decision' },
    { kind: 'new_formulation', utterance: 'Licht bitte an', general_learning: { status: 'failed' } },
  ]);
  assert.match(panel.children[1].textContent, /Ungeprüfter Kandidat.*Kerzenromantik/);
  assert.match(panel.children[2].textContent, /Prüfung gescheitert.*missing reference/);
  assert.match(panel.children[3].textContent, /Bewusst nichts gelernt.*Model decision/);
  assert.match(panel.children[4].textContent, /Neue Formulierung verknüpft.*Allgemeine Lernprüfung gescheitert/);
});

test('renders user wording as text and explains an empty history', () => {
  const text = '<img src=x onerror=alert(1)>';
  assert.match(render([{ kind: 'pending', utterance: text }]).children[1].textContent, /<img/);
  assert.match(render([]).children[1].textContent, /Noch keine Formulierungsprüfung/);
});
