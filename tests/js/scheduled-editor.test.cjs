const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');

function editor(type, end = '') {
  const context = { elements: {
    taskScheduleType: { value: type }, taskEndsAt: { value: end },
    taskOnceAt: { value: '2099-02-01T09:00' }, taskTime: { value: '09:00' },
    taskIntervalValue: { value: '30' }, taskIntervalUnit: { value: '60' },
    taskWeekdays: { querySelectorAll: () => [{ value: '0' }, { value: '4' }] },
  }};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function taskSchedulePayload()'),
    source.indexOf('  async function deleteTask(')), context);
  return context;
}

test('end time survives all schedule types and clears without a replacement value', () => {
  for (const type of ['once', 'delay', 'interval', 'daily', 'weekly']) {
    const c = editor(type, '2099-03-01T13:06');
    assert.equal(c.taskSchedulePayload().schedule.ends_at, new Date('2099-03-01T13:06').toISOString());
    c.elements.taskEndsAt.value = '';
    assert.equal('ends_at' in c.taskSchedulePayload().schedule, false);
  }
});

test('editor rejects invalid or expired end dates and an end before the one-shot run', () => {
  for (const end of ['not-a-date', '2000-01-01T00:00', '2099-01-01T00:00']) {
    assert.throws(() => editor('once', end).taskSchedulePayload(), /Enddatum/);
  }
});

test('task list displays the saved end date', () => {
  const c = { conversationTime: value => value };
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('  function taskSchedule(task)'),
    source.indexOf('  function renderTaskList()')), c);
  assert.match(c.taskSchedule({ schedule_type: 'daily', next_run_at: '2099-01-01T08:00:00Z',
    schedule: { ends_at: '2099-02-01T12:06:00Z' } }), /Ende: 2099-02-01T12:06:00Z/);
});
