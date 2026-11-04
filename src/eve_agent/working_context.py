"""Move context frames to database references according to measured capacity only."""
from __future__ import annotations

import base64
import json
import uuid
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from .context_budget import WorkingContextBudgetError
from .working_memory import WorkingMemoryStore


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


class WorkingMemorySession:
    def __init__(self, agent, text, images, trace_id, *, isolated=False,
                 retention_class='standard'):
        self.agent = agent
        self.isolated = isolated
        self.store = WorkingMemoryStore(agent.memory.database)
        self.workspace_id = (
            self.store.create(title='Temporäres Lernmaterial', retention_class=retention_class)
            if isolated else self.store.open(agent.conversation_id)
        )
        self.input = {'text': text, 'images': images, 'trace_id': trace_id}
        from .scheduled_execution import input_metadata, scheduled_metadata
        self.input['input_metadata'] = input_metadata()
        execution = scheduled_metadata()
        if execution is not None:
            self.input['scheduled_execution'] = execution
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
        # These attempts belong to the entire user/scheduled turn. A context
        # reset or workspace switch must not create a fresh retry allowance.
        self.recovery_attempts = {}
        self.finished = False
        self.context_number = 0
        self.journal = None
        self.journal_reference = None
        self.reset_reason = 'capacity'
        self.defer_images = False
        self.last_rejected_measurement = None
        self.last_checkpoint_signature = None
        self.checkpoint_capture = None
        self.delta_reference = None
        self.delta_signature = None
        agent._working_memory_context = self.identity()

    def identity(self):
        return {'workspace_id': self.workspace_id, 'work_turn_id': self.turn_id,
                'request_reference': self.request['reference']}

    def entry(self):
        manifest = self.store.manifest(self.workspace_id, current_turn_id=self.turn_id)
        self._update_delta(manifest['checkpoint_reference'])
        with self.store.database.connect(lifecycle_audit=False) as c:
            latest = c.execute("SELECT id,status,request_id AS request_reference,answer_id AS model_answer_reference,"
                "error_id AS error_reference FROM memory_work_turns WHERE workspace_id=? AND id!=? "
                "AND status!='running' ORDER BY updated_at DESC,id DESC LIMIT 1",
                (self.workspace_id, self.turn_id)).fetchone()
        return {**self.identity(), 'revision': manifest['revision'],
                'latest_turn_outcome': dict(latest) if latest else None,
                'checkpoint_reference': manifest['checkpoint_reference'],
                **({'execution_delta_reference': self.delta_reference} if self.delta_reference else {}),
                'uncertain_call_count': len(manifest['uncertain_calls']),
                'unfinished_turn_count': len(manifest['unfinished_turns']),
                'last_unfinished_turn': manifest['unfinished_turns'][-1] if manifest['unfinished_turns'] else None,
                'activity': self.store.activity(self.workspace_id),
                'access': 'working_memory', 'checkpoint_author': 'model',
                'checkpoint_is_verified_fact': False}

    def _update_delta(self, checkpoint):
        """References after the checkpoint, including a previous terminal turn.

        Model answers remain labelled as such; none becomes provider evidence.
        The same immutable delta is reused until its database records change.
        """
        if not checkpoint:
            return
        since = self.store.describe(self.workspace_id, checkpoint)['created_at']
        calls = [call for call in self.store.calls(self.workspace_id)['items'] if call['created_at'] > since
                 and not (call['capability'] == 'working_memory' and call['operation'] == 'checkpoint')]
        with self.store.database.connect(lifecycle_audit=False) as c:
            turns = [dict(row) for row in c.execute(
                "SELECT id,status,request_id AS request_reference,answer_id AS model_answer_reference,"
                "error_id AS error_reference FROM memory_work_turns "
                "WHERE workspace_id=? AND id!=? AND status!='running' AND updated_at>? ORDER BY created_at,id",
                (self.workspace_id, self.turn_id, since))]
        delta = {'calls': calls, 'terminal_turns': turns, 'model_answers_are_verified_facts': False}
        signature = encoded([checkpoint, delta])
        if signature != self.delta_signature:
            self.delta_reference = self.archive_frame(delta, kind='execution_delta')['reference']
            self.delta_signature = signature

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
            self.last_checkpoint_signature = self._material_signature()
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
        self.last_checkpoint_signature = None
        self.checkpoint_capture = None
        self.delta_reference = None
        self.delta_signature = None
        self.agent._working_memory_context = self.identity()

    def _material_signature(self):
        """Returned evidence, independent of queries, clocks and receipt IDs."""
        inputs = set()
        for call in self.store.calls(self.workspace_id)['items']:
            if call['turn_id'] != self.turn_id or call['status'] != 'returned':
                continue
            capability, operation = call['capability'], call['operation']
            if capability in {'eve_runtime', 'clock'} or (capability == 'working_memory' and operation != 'read'):
                continue
            parameters = self.store.value(self.workspace_id, call['request_reference'])
            result = self.store.value(self.workspace_id, call['result_reference'])
            if isinstance(result, dict) and result.get('status') in {'error', 'failed', 'rejected', 'outcome_uncertain'}:
                continue
            if capability == 'working_memory' and operation == 'read' and 'content' in result:
                inputs.add(encoded([capability, operation,
                    self.store.read_identity(self.workspace_id, parameters, result)[1]]))
                continue
            from .result_identity import provider_evidence, value_digest
            if capability == 'working_memory':
                continue
            outcome = value_digest(provider_evidence(capability, operation, result))
            inputs.add(encoded([capability, operation, outcome]))
        return encoded([self.request['reference'], sorted(inputs)])

    def capture_checkpoint(self, messages, core_prompt, reason, *, completion=None):
        """Persist a model-authored state before externalizing its source frames.

        Only the checkpoint tool is offered. No provider can be executed here;
        Python validates protocol, revision and workspace references only.
        """
        from .llm import LocalLLMError
        from .working_memory import contract
        request = getattr(self.agent.llm, 'request_working_checkpoint', None)
        signature = self._material_signature()
        if completion is not None:
            signature = encoded([signature, completion])
        if not callable(request) or signature == self.last_checkpoint_signature:
            return
        revision = self.entry()['revision']
        operation = deepcopy(contract()['operations']['checkpoint'])
        schema = operation['parameters_schema']
        schema['properties']['expected_revision'] = {'type': 'integer', 'const': revision}
        schema['properties']['state']['minProperties'] = 1
        evidence = {self.request['reference']}
        completion_reference = None
        if completion is not None:
            completion_reference = self.store.put(self.workspace_id, {'content': completion,
                'author': 'model', 'verified_fact': False}, kind='model_answer', source='assistant',
                turn_id=self.turn_id)['reference']
            evidence.add(completion_reference)
        previous = self.entry()['checkpoint_reference']
        if previous:
            evidence.add(previous)
        evidence.update(self.tool_refs[id(frame)]['reference'] for frame in messages if id(frame) in self.tool_refs)
        # Historical sources are valid too. checkpoint() resolves exact IDs and
        # observation aliases against the workspace inside the write transaction.
        schema['properties']['references'] = {'type': 'array', 'minItems': 1,
            'items': {'type': 'string', 'minLength': 1}}
        schema['required'] = ['state', 'expected_revision', 'references']
        tools = [{'type': 'function', 'function': {'name': 'working_memory__checkpoint',
                  'description': operation['description'] + ' Persistence only; do not continue the task in this call.',
                  'parameters': schema}}]
        control = {'role': 'user', 'content': encoded({'checkpoint_boundary': {
            'reason': reason, 'expected_revision': revision,
            'request_reference': self.request['reference'],
            'previous_checkpoint_reference': self.entry()['checkpoint_reference'],
            'available_source_references': sorted(evidence),
            **({'completion_reference': completion_reference} if completion_reference else {})}})}
        frames = [dict(message) for message in messages]
        clones = []
        for original, frame in zip(messages, frames):
            if id(original) in self.tool_refs:
                self.tool_refs[id(frame)] = self.tool_refs[id(original)]
                clones.append(id(frame))
        if completion is not None:
            frames.append({'role': 'assistant', 'content': completion})
        frames.append(control)
        call_id = None
        try:
            self._externalize_tools(frames, keep_read_round=False, tools=tools)
            if not self._fits(frames, tools):
                self._defer_structures(frames)
            if not self._fits(frames, tools):
                original = self.archive_frame(messages, kind='checkpoint_source')
                frames = self._seed(core_prompt, tools) + [{'role': 'user', 'content': encoded({
                    'checkpoint_source_reference': original['reference'], 'source_content_in_context': False})}, control]
            if not self._fits(frames, tools):
                raise WorkingContextBudgetError(self.workspace_id, 'Checkpoint-Anfrage passt nicht in das Modellbudget.')
            context = self.archive_frame(frames, kind='checkpoint_context')
            response = request(frames, tools)
            self.archive_frame(response, kind='checkpoint_response')
            calls = response.get('tool_calls') or []
            if len(calls) != 1 or calls[0].get('name') != 'working_memory__checkpoint':
                raise ValueError('Checkpoint-Protokoll: genau ein Checkpoint-Aufruf erforderlich')
            parameters = calls[0].get('arguments')
            Draft202012Validator(schema).validate(parameters)
            if not isinstance(calls[0].get('id'), str) or not calls[0]['id']:
                raise ValueError('Checkpoint-Protokoll: Aufruf-ID fehlt')
            # Model call IDs are scoped to one RPC. Internal persistence RPCs
            # need their own journal identity when a server reuses those IDs.
            call_id = self.store.start_call(self.workspace_id, self.turn_id, 'checkpoint_' + uuid.uuid4().hex,
                'working_memory', 'checkpoint', 'write', parameters)
            self.store.dispatch_call(self.workspace_id, call_id)
            # checkpoint() atomically rejects stale revisions and foreign evidence.
            result = self.execute('checkpoint', parameters)
            self.store.finish_call(self.workspace_id, self.turn_id, call_id, result)
            self.checkpoint_capture = {'status': 'saved', 'reason': reason,
                'checkpoint_reference': result['checkpoint']['reference'], 'context_reference': context['reference']}
        except (LocalLLMError, ValueError, KeyError, ValidationError, WorkingContextBudgetError) as exc:
            # A failed serialization must never overwrite a valid previous state.
            self.checkpoint_capture = {'status': 'failed', 'reason': reason,
                'class': type(exc).__name__, 'message': str(exc)}
            if call_id is not None:
                self.store.finish_call(self.workspace_id, self.turn_id, call_id, self.checkpoint_capture)
            self.archive_frame(self.checkpoint_capture, kind='checkpoint_error')
        finally:
            for identifier in clones:
                self.tool_refs.pop(identifier, None)
        # One serialization per unchanged set of source results, also on failure.
        self.last_checkpoint_signature = signature

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
        if getattr(self.agent, 'conversations', None) and self.agent.conversation_id:
            data['conversation_assets'] = {'conversation_id': self.agent.conversation_id,
                'access': 'conversation_assets.list',
                'current_input_ids': [f'input:{index}' for index in range(len(self.input['images']))]}
        if self.input.get('input_metadata'):
            data.update(self.input['input_metadata'])
        if self.input.get('scheduled_execution') is not None:
            data['scheduled_execution'] = self.input['scheduled_execution']
        if self.checkpoint_capture is not None:
            data['checkpoint_capture'] = self.checkpoint_capture
        if entry['checkpoint_reference']:
            data['execution_delta_reference'] = self.delta_reference
            data['checkpoint_content_in_context'] = bool(include_checkpoint)
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
        switched = bool(self.pending_workspace)
        if self.pending_workspace:
            self.capture_checkpoint(messages, core_prompt, 'workspace_open')
            self.switch_workspace()
            messages = self._seed(core_prompt, tools)
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
        if not switched:
            self.capture_checkpoint(messages, core_prompt, self.reset_reason if self.reset_requested else 'capacity')
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
        """One repair per model failure category, surviving new tools/contexts."""
        from .llm import EmptyModelResponseError, LocalLLMOutputLimitError
        category = ('empty_model_response' if isinstance(error, EmptyModelResponseError) else
                    'output_limit' if isinstance(error, LocalLLMOutputLimitError) else 'provider_context_rejection')
        signature = self._material_signature()
        attempts = self.recovery_attempts.get(category, 0)
        repeated = attempts > 0 or signature == self.last_recovery_signature
        self.archive_frame({'class': type(error).__name__, 'message': str(error),
                            'partial_response': getattr(error, 'partial_response', ''),
                            'category': category, 'previous_recovery_attempts': attempts,
                            'new_material_since_last_recovery': signature != self.last_recovery_signature,
                            'recovery_allowed': not repeated}, kind='model_context_error')
        if repeated:
            if isinstance(error, (EmptyModelResponseError, LocalLLMOutputLimitError)):
                raise error
            raise WorkingContextBudgetError(self.workspace_id, 'Der Modellserver lehnt auch den frischen Kontext ab.') from error
        self.recovery_attempts[category] = attempts + 1
        self.last_recovery_signature = signature
        refresh = getattr(self.agent.llm, 'runtime_model_info', None)
        if callable(refresh):
            refresh(refresh=True)
        self.reset_requested = True
        self.reset_reason = category
        self.defer_images = True

    def finish(self, status, value):
        if not self.finished:
            self.store.finish_turn(self.workspace_id, self.turn_id, status, value)
            self.agent._working_memory_context = {**(self.agent._working_memory_context or self.identity()),
                'activity': self.store.activity(self.workspace_id, turn_id=self.turn_id)}
            if status in {'cancelled', 'failed'} and not self.isolated:
                self.agent.conversations.preserve_interrupted_turn(self.turn_id)
            self.finished = True
