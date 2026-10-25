"""Move context frames to database references according to measured capacity only."""
from __future__ import annotations

import base64
import json
import uuid

from .context_budget import WorkingContextBudgetError
from .working_memory import WorkingMemoryStore


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


class WorkingMemorySession:
    def __init__(self, agent, text, images, trace_id, *, isolated=False,
                 retention_class='standard'):
        self.agent = agent
        self.store = WorkingMemoryStore(agent.memory.database)
        self.workspace_id = (
            self.store.create(title='Temporäres Lernmaterial', retention_class=retention_class)
            if isolated else self.store.open(agent.conversation_id)
        )
        self.input = {'text': text, 'images': images, 'trace_id': trace_id}
        self.turn_id, self.request = self.store.begin_turn(self.workspace_id, agent.conversation_id, self.input, trace_id)
        self.original_context = None
        self.tool_refs = {}
        self.read_frames = set()
        self.read_requests = {}
        self.last_round_start = None
        self.reset_requested = False
        self.pending_workspace = None
        self.latest_budget = None
        self.last_recovery_signature = None
        self.finished = False
        self.context_number = 0
        self.journal = None
        self.journal_reference = None
        self.reset_reason = 'capacity'
        self.defer_images = False
        self.last_rejected_measurement = None
        agent._working_memory_context = self.identity()

    def identity(self):
        return {'workspace_id': self.workspace_id, 'work_turn_id': self.turn_id,
                'request_reference': self.request['reference']}

    def entry(self):
        manifest = self.store.manifest(self.workspace_id, current_turn_id=self.turn_id)
        return {**self.identity(), 'revision': manifest['revision'],
                'checkpoint_reference': manifest['checkpoint_reference'],
                'uncertain_call_count': len(manifest['uncertain_calls']),
                'unfinished_turn_count': len(manifest['unfinished_turns']),
                'last_unfinished_turn': manifest['unfinished_turns'][-1] if manifest['unfinished_turns'] else None,
                'activity': self.store.activity(self.workspace_id),
                'access': 'working_memory', 'checkpoint_author': 'model',
                'checkpoint_is_verified_fact': False}

    def execute(self, operation, parameters):
        p = parameters; s = self.store; w = self.workspace_id
        if operation == 'status':
            return {**s.manifest(w, current_turn_id=self.turn_id), 'context_budget': self.latest_budget}
        if operation == 'list':
            return s.list_objects(w, **p)
        if operation == 'inspect':
            return {**s.inspect(w, **p), 'retrieval_observation': s.retrieval_observation(w, operation, p)}
        if operation == 'read':
            p = dict(p); as_image = p.pop('as_image', False)
            if as_image:
                if p.get('offset', 0) or p.get('limit') is not None:
                    raise ValueError('Bilder können nur vollständig als Bild gelesen werden')
                value = s.pointer(s.value(w, p['reference']), p.get('pointer', ''))
                if isinstance(value, bytes):
                    media = s.describe(w, p['reference'])['media_type']
                    value = 'data:' + media + ';base64,' + base64.b64encode(value).decode()
                if not isinstance(value, str) or not value.startswith('data:image/'):
                    raise ValueError('Referenz enthält kein eingebettetes Bild')
                return {'reference': p['reference'], 'resources': [{'type': 'image', 'content': value}], 'complete': True}
            return {**s.read(w, **p), 'retrieval_observation': s.retrieval_observation(w, operation, p)}
        if operation == 'save':
            return s.put(w, p['value'], title=p.get('title', ''), references=p.get('references', ()), turn_id=self.turn_id)
        if operation == 'checkpoint':
            result = s.checkpoint(w, p['state'], expected_revision=p['expected_revision'],
                                  references=p.get('references', ()), turn_id=self.turn_id)
            self.agent._working_memory_context = {**self.identity(), 'checkpoint_reference': result['checkpoint']['reference']}
            return result
        if operation == 'review_call':
            return s.review_call(w, p['call_reference'], p['decision'], p['evidence_references'],
                                 allow_retry=p['allow_retry'], turn_id=self.turn_id)
        if operation == 'reset_context':
            self.reset_requested = True
            self.reset_reason = 'model_requested'
            return {'status': 'accepted', 'workspace_id': w, 'originals_retained': True}
        if operation == 'events':
            return s.events(w, **p)
        if operation == 'workspaces':
            return s.workspaces()
        if operation == 'open':
            if p.get('create') and p.get('workspace_id'):
                raise ValueError('Entweder neuen Arbeitsstand anlegen oder vorhandenen öffnen')
            if p.get('create'):
                new_id = str(uuid.uuid4())
                # open() intentionally only creates when no binding exists; a
                # new task gets its own explicit identity here.
                with s.database.connect(lifecycle_audit=False) as c:
                    from .working_memory import _now
                    now = _now()
                    c.execute('INSERT INTO memory_workspaces '
                              '(id,title,created_at,updated_at,last_accessed_at) VALUES (?,?,?,?,?)',
                              (new_id, p.get('title') or 'Arbeitsstand', now, now, now))
            else:
                new_id = p.get('workspace_id')
                if not new_id:
                    raise ValueError('workspace_id oder create=true erforderlich')
            manifest = s.manifest(new_id)
            if new_id == w:
                return {'status': 'completed', 'already_current': True, 'workspace': manifest}
            self.pending_workspace = new_id
            self.reset_requested = True
            self.reset_reason = 'workspace_open'
            return {'status': 'accepted', 'switch_after_tool_round': True, 'workspace': manifest}
        if operation == 'set_status':
            return s.set_status(w, p['status'])
        if operation == 'set_pinned':
            return s.set_pinned(w, p['pinned'])
        raise ValueError('Unbekannte Arbeitsgedächtnisoperation')

    def switch_workspace(self):
        if not self.pending_workspace:
            return
        self.store.finish_turn(self.workspace_id, self.turn_id, 'completed', {'handoff_workspace': self.pending_workspace})
        self.workspace_id = self.store.open(self.agent.conversation_id, workspace_id=self.pending_workspace)
        self.pending_workspace = None
        self.turn_id, self.request = self.store.begin_turn(self.workspace_id, self.agent.conversation_id, self.input,
                                                         self.input['trace_id'])
        self.original_context = None
        self.tool_refs.clear(); self.read_frames.clear(); self.read_requests.clear(); self.last_round_start = None
        self.last_recovery_signature = None
        self.agent._working_memory_context = self.identity()

    def archive_frame(self, message, kind='context_frame'):
        return self.store.put(self.workspace_id, message, kind=kind, source='system', turn_id=self.turn_id)

    def tool_frame(self, message, descriptor, *, readable=False, selection=None):
        self.tool_refs[id(message)] = descriptor
        if readable:
            self.read_frames.add(id(message))
        if selection is not None:
            self.read_requests[id(message)] = selection

    def _budget(self, messages, tools):
        measure = getattr(self.agent.llm, 'context_budget', None)
        if not callable(measure):
            return None
        budget = measure(messages, tools)
        self.latest_budget = budget
        if budget is not None and not budget['fits']:
            measurement = (budget.get('input_tokens'), budget.get('context_tokens'))
            if measurement != self.last_rejected_measurement:
                self.store.put(self.workspace_id, budget, kind='context_measurement', source='system', turn_id=self.turn_id)
                self.last_rejected_measurement = measurement
        return budget

    def _fits(self, messages, tools):
        result = self._budget(messages, tools)
        return result is None or bool(result['fits'])

    def _reference(self, descriptor):
        return {'stored_result': descriptor, 'content_in_context': False,
                'original_available': True, 'access': 'working_memory.read',
                'structure_access': 'working_memory.inspect',
                'structure': self.store.inspect(self.workspace_id, descriptor['reference'])}

    @staticmethod
    def _defer_structures(messages):
        """A structural outline is data too; never let it exhaust the context."""
        for message in messages:
            if message.get('role') != 'tool':
                continue
            try:
                value = json.loads(message['content'])
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and 'stored_result' in value and 'structure' in value:
                del value['structure']
                value['structure_in_context'] = False
                message['content'] = encoded(value)

    def _externalize_tools(self, messages, *, keep_read_round=True, tools=None):
        # One oversized result must not hide every smaller receipt as well.
        # Size determines removal order only; the serving model determines fit.
        frames = sorted(((index, message) for index, message in enumerate(messages)
                         if id(message) in self.tool_refs),
                        key=lambda pair: len(encoded(pair[1])), reverse=True)
        for index, message in frames:
            descriptor = self.tool_refs.get(id(message))
            if not descriptor:
                continue
            if (keep_read_round and id(message) in self.read_frames and self.last_round_start is not None
                    and index >= self.last_round_start):
                continue
            if tools is not None and self._fits(messages, tools):
                break
            value = self._reference(descriptor)
            if id(message) in self.read_requests:
                value['requested_selection'] = self.read_requests[id(message)]
            message['content'] = encoded(value)

    def _seed(self, core_prompt, tools, *, include_checkpoint=True, include_request=True, include_journal=True):
        entry = self.entry()
        data = {'working_memory': entry, 'context': 'fresh', 'originals_retained': True,
                'transition': {'reason': self.reset_reason, 'prepared': True,
                               'requested_reset_completed': self.reset_reason == 'model_requested'},
                'execution_journal_reference': self.journal_reference}
        standing_reader = getattr(self.agent.memory, 'standing_instructions', None)
        if callable(standing_reader):
            data['standing_memory'] = standing_reader(telemetry_context={
                'trace_id': self.input['trace_id'], 'turn_id': self.input['trace_id'],
                'conversation_id': self.agent.conversation_id})
        if self.original_context:
            data['previous_context_reference'] = self.original_context['reference']
        if include_checkpoint and entry['checkpoint_reference']:
            data['model_authored_checkpoint'] = self.store.value(self.workspace_id, entry['checkpoint_reference'])
        request = self.input['text'] if include_request else {'request_reference': self.request['reference'],
                                                             'access': 'working_memory.read'}
        content = request if isinstance(request, str) else encoded(request)
        if self.defer_images and self.input['images']:
            data['deferred_images_reference'] = self.request['reference']
        if include_request and self.input['images'] and not self.defer_images:
            content = [{'type': 'text', 'text': content},
                       *[{'type': 'image_url', 'image_url': {'url': image}} for image in self.input['images']]]
        if include_journal:
            data['execution_activity'] = self.store.activity(self.workspace_id, turn_id=self.turn_id)
        return [{'role': 'system', 'content': core_prompt}, {'role': 'user', 'content': content},
                {'role': 'user', 'content': 'Fortsetzung der begonnenen Aufgabe. Laufzeitdaten und modellformulierter Arbeitsstand: '
                 + encoded(data)}]

    def _record_context(self, messages, reason):
        obj = self.archive_frame(messages, kind='context_request')
        budget = self.latest_budget or {}
        with self.store.database.connect(lifecycle_audit=False) as c:
            from .working_memory import _now
            c.execute('INSERT INTO memory_work_contexts VALUES (?,?,?,?,?,?,?,?)',
                      (str(uuid.uuid4()), self.workspace_id, self.turn_id, reason, obj['reference'],
                       budget.get('input_tokens'), budget.get('context_tokens'), _now()))
        self.context_number += 1
        telemetry = getattr(self.agent, 'telemetry', None)
        if telemetry:
            telemetry.event('working_memory', 'context', details={**self.identity(), 'reason': reason,
                'context_reference': obj['reference'], 'budget': budget})

    def prepare(self, messages, tools, capabilities, state, core_prompt, publish, *, force=False):
        """Return a valid bounded chat frame sequence, retaining all originals."""
        if self.pending_workspace:
            self.switch_workspace()
            force = True
        if not force and not self.reset_requested and self._fits(messages, tools):
            if self.context_number == 0:
                self._record_context(messages, 'initial')
            return messages, tools, None
        if self.original_context is None:
            self.original_context = self.archive_frame(messages, kind='archived_context')
        self._externalize_tools(messages, tools=tools)
        if not self._fits(messages, tools):
            self._defer_structures(messages)
        if not force and not self.reset_requested and self._fits(messages, tools):
            self._record_context(messages, 'original_results_referenced')
            return messages, tools, None
        self.journal = self.store.calls(self.workspace_id)
        self.journal_reference = self.archive_frame(self.journal, kind='execution_journal')['reference']
        # A complete assistant/tool group is retained, never half an OpenAI call.
        tail = messages[self.last_round_start:] if self.last_round_start is not None else []
        if self.defer_images:
            tail = [m for m in tail if not (isinstance(m.get('content'), list)
                    and any(p.get('type') in {'image','image_url'} for p in m['content']))]
            for message in tail:
                descriptor = self.tool_refs.get(id(message))
                if not descriptor:
                    continue
                try:
                    body = json.loads(message['content'])
                except (TypeError, ValueError):
                    continue
                if isinstance(body, dict) and any(r.get('type') == 'image' for r in body.get('resources', [])):
                    message['content'] = encoded({**self._reference(descriptor), 'image_content_deferred': True})
        seed = self._seed(core_prompt, tools)
        if not self._fits(seed, tools):
            seed = self._seed(core_prompt, tools, include_journal=False)
        if not self._fits(seed, tools):
            seed = self._seed(core_prompt, tools, include_checkpoint=False, include_journal=False)
        if not self._fits(seed, tools):
            seed = self._seed(core_prompt, tools, include_checkpoint=False, include_request=False, include_journal=False)
        new_bindings = None
        if not self._fits(seed, tools):
            state['loaded_capabilities'] = []
            tools, new_bindings = publish(capabilities, [])
            seed = self._seed(core_prompt, tools, include_checkpoint=False, include_request=False, include_journal=False)
        if not self._fits(seed, tools):
            raise WorkingContextBudgetError(self.workspace_id, 'Bereits der technische Einstieg überschreitet das Modellbudget.')
        fresh = seed + tail
        self.last_round_start = len(seed) if tail else None
        if not self._fits(fresh, tools):
            self._externalize_tools(fresh, keep_read_round=False, tools=tools)
        if not self._fits(fresh, tools):
            self._defer_structures(fresh)
        if not self._fits(fresh, tools):
            # Contracts can outweigh even reference-only results. They remain
            # reloadable; no provider or domain is preferred by Python.
            state['loaded_capabilities'] = []
            tools, new_bindings = publish(capabilities, [])
        if not self._fits(fresh, tools):
            fresh = seed
            self.last_round_start = None
        if not self._fits(fresh, tools):
            raise WorkingContextBudgetError(self.workspace_id, 'Benötigter Abruf muss weiter unterteilt werden.')
        self.reset_requested = False
        self._record_context(fresh, 'fresh_context')
        return fresh, tools, new_bindings

    def recover(self, messages, error):
        """Retry only if a context reset can change the rejected model input."""
        signature = encoded([self.request['reference'], self.entry()['checkpoint_reference'],
                             [m.get('tool_calls') for m in messages if m.get('tool_calls')]])
        if signature == self.last_recovery_signature:
            raise WorkingContextBudgetError(self.workspace_id, 'Der Modellserver lehnt auch den frischen Kontext ab.') from error
        self.last_recovery_signature = signature
        refresh = getattr(self.agent.llm, 'runtime_model_info', None)
        if callable(refresh):
            refresh(refresh=True)
        self.archive_frame({'class': type(error).__name__, 'message': str(error),
                            'partial_response': getattr(error, 'partial_response', '')}, kind='model_context_error')
        self.reset_requested = True
        self.reset_reason = 'provider_context_rejection'
        self.defer_images = True

    def finish(self, status, value):
        if not self.finished:
            self.store.finish_turn(self.workspace_id, self.turn_id, status, value)
            self.agent._working_memory_context = {**(self.agent._working_memory_context or self.identity()),
                'activity': self.store.activity(self.workspace_id, turn_id=self.turn_id)}
            self.finished = True
