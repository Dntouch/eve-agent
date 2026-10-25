"""Small factual failure reports shared by persistence, UI and retry context."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid
import urllib.error

from .memory import redact_sensitive
from .answer_stream import AnswerStreamMismatchError


ANSWER_STREAM_MISMATCH_REASON = (
    'Die ausgegebene Antwort und die endgültige Antwort stimmen nicht überein. '
    'EVE konnte die Antwort deshalb nicht korrekt abschließen.'
)


def normalize_failure_report(report):
    """Recognize the recorded invariant error in older, unclassified cards."""
    technical = str(report.get('technical') or '')
    if report.get('category', 'unknown') == 'unknown' and (
        'finale Antworttext stimmt nicht mit dem veröffentlichten Stream überein' in technical
        or 'finale Antworttext widerspricht dem bereits veröffentlichten Answer-Stream' in technical
    ):
        return {**report, 'category':'answer_stream_mismatch', 'reason':ANSWER_STREAM_MISMATCH_REASON}
    return report


def failure_report(exc, *, turn_id=None, input_text='', conversation_id=None, tool_events=(), working_activity=None):
    chain, current = [], exc
    while current is not None and all(current is not c for c in chain):
        chain.append(current)
        current = current.__cause__
    technical = redact_sensitive(' | '.join(f'{type(e).__name__}: {e}' for e in chain))[:6000]
    category = 'unknown'
    reason = 'Der Vorgang konnte nicht abgeschlossen werden. Der genaue Grund ist noch unbekannt.'
    codes = {str(getattr(e, 'provider_code', '')) for e in chain}
    if codes & {'exceed_context_size_error', 'context_length_exceeded', 'working_context_limit'} or 'exceeds the available context size' in technical or 'request exceeds the context window' in technical:
        category, reason = 'context_limit', 'Die Anfrage überschreitet das Kontextfenster des lokalen Modells.'
    elif (any(isinstance(e, AnswerStreamMismatchError) for e in chain)
          or 'finale Antworttext stimmt nicht mit dem veröffentlichten Stream überein' in technical
          or 'finale Antworttext widerspricht dem bereits veröffentlichten Answer-Stream' in technical):
        category = 'answer_stream_mismatch'
        reason = ANSWER_STREAM_MISMATCH_REASON
    elif any(isinstance(e, urllib.error.HTTPError) for e in chain):
        status = next(e.code for e in chain if isinstance(e, urllib.error.HTTPError))
        category, reason = 'http_error', f'Der angesprochene Server hat die Anfrage mit HTTP {status} abgelehnt.'
    elif any(isinstance(e, sqlite3.IntegrityError) for e in chain):
        category, reason = 'storage', 'Die Antwort konnte wegen eines Datenbankkonflikts nicht gespeichert werden.'
    elif any(isinstance(e, TimeoutError) for e in chain) or 'nicht innerhalb von' in technical:
        category, reason = 'timeout', 'Beim Warten auf einen Verarbeitungsschritt wurde das Zeitlimit erreicht.'
    elif any(getattr(e, 'provider_code', None) for e in chain):
        category, reason = 'model_server', 'Der lokale Modellserver hat einen Fehler gemeldet.'
    elif 'weder Antwort noch Tool-Aufruf' in technical:
        category, reason = 'empty_model_response', 'Vom lokalen Modell kam keine verwertbare Antwort. Der genaue Servergrund wurde nicht gemeldet.'
    elif 'OutputLimit' in technical:
        category, reason = 'output_limit', 'Das lokale Modell hat sein Ausgabelimit erreicht.'
    response_evidence = next((e.response_evidence for e in chain if hasattr(e, 'response_evidence')), None)
    last_step = None
    steps = []
    for event in tool_events:
        result = event.get('result') or {}
        if isinstance(result, dict):
            request = result.get('request') or {}
            response = result.get('response') or {}
            body = response.get('body') if isinstance(response, dict) else None
            last_step = {'tool': event.get('tool'), 'operation': event.get('operation'),
                         'status': event.get('status'), 'path': redact_sensitive(str(request.get('path') or '')),
                         'http_status': response.get('status') if isinstance(response, dict) else None,
                         'result_count': len(body) if isinstance(body, list) else result.get('total_matches')}
            steps.append(last_step)
    hint = ('Grenze die benötigten Informationen ein und nutze gezielte Memory-Abfragen.'
            if category == 'context_limit'
            else 'Prüfe den Fehlerbericht und setze die ursprüngliche Aufgabe mit der nötigen Korrektur fort.')
    return {**({'execution_observation': working_activity} if working_activity is not None else {}),
            'turn_id': turn_id or uuid.uuid4().hex, 'conversation_id': conversation_id,
            'created_at': datetime.now(timezone.utc).isoformat(), 'category': category,
            'title': 'Die Aufgabe konnte nicht abgeschlossen werden.', 'reason': reason,
            'technical': technical, 'last_step': last_step, 'tool_steps': steps,
            **({'model_response_evidence': response_evidence, 'resumable': True} if response_evidence is not None else {}),
            'input_text': redact_sensitive(str(input_text or '')), 'retry_hint': hint}


def resume_failure_request(conversations, conversation_id, retry_context):
    """Build continuation data from the stored report, never client-supplied evidence."""
    if not isinstance(retry_context, dict) or set(retry_context) != {'source_turn_id', 'correction'}:
        raise ValueError('Ungültiger Wiederholungskontext')
    source, correction = retry_context['source_turn_id'], retry_context['correction']
    if not isinstance(source, str) or not source.strip() or not isinstance(correction, str):
        raise ValueError('Fehlversuch oder Korrekturhinweis ungültig')
    report = next((item for item in conversations.failures(conversation_id) if item['turn_id'] == source), None)
    if report is None:
        raise ValueError('Fehlversuch gehört nicht zu dieser Unterhaltung')
    data = {key: report[key] for key in ('turn_id', 'category', 'reason', 'technical', 'last_step',
            'working_memory', 'model_response_evidence') if key in report}
    import json
    text = str(report.get('input_text') or '') + '\n\nWiederaufnahme (gespeicherte Laufzeitdaten):\n' + json.dumps(data, ensure_ascii=False)
    if correction.strip():
        text += '\n\nKorrekturhinweis des Benutzers:\n' + correction.strip()
    return text, report
