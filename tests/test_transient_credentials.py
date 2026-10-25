import json
import threading
import unittest
from urllib.parse import quote

from eve_agent.memory import redact_sensitive
from eve_agent.transient_credentials import (
    credential_scope, current_credentials, resolve_credentials,
)


class TransientCredentialTest(unittest.TestCase):
    def test_model_sees_opaque_reference_and_execution_resolves_exact_value(self):
        secret = 'Späce &;"$value'
        text = "Passwort: '" + secret + "'\nSSID: Testnetz"
        with credential_scope(text) as scope:
            reference = '{{eve_secret:' + next(iter(scope.values)) + '}}'
            self.assertNotIn(secret, scope.model_text)
            self.assertIn(reference, scope.model_text)
            self.assertIn('SSID: Testnetz', scope.model_text)
            self.assertEqual({'env': {'WIFI': secret}}, resolve_credentials({'env': {'WIFI': reference}}))
            self.assertEqual(quote(secret, safe=''), resolve_credentials(reference[:-2] + '|url}}'))
            self.assertNotIn(secret, scope.contract())
            self.assertEqual('[REDACTED]', redact_sensitive(secret))
        self.assertEqual({}, scope.values)
        self.assertEqual([], scope.variants)
        self.assertIsNone(current_credentials())
        with self.assertRaises(ValueError): resolve_credentials(reference)

    def test_repeated_raw_value_outside_assignment_is_also_removed_from_model_text(self):
        with credential_scope('Passwort: example-transient-123\nAgain: example-transient-123') as scope:
            self.assertNotIn('example-transient-123', scope.model_text)
            self.assertIn('[REDACTED]', scope.model_text)

    def test_cleanup_and_exception_sanitization_on_failure(self):
        secret = 'exception-secret-456'
        with self.assertRaises(RuntimeError) as failure:
            with credential_scope('Password: ' + secret) as scope:
                raise RuntimeError('request failed: ' + secret)
        self.assertNotIn(secret, str(failure.exception))
        self.assertIsNone(current_credentials())
        self.assertEqual({}, scope.values)

    def test_secret_references_are_isolated_between_requests_and_threads(self):
        with credential_scope('Password: one-secret') as first:
            ref = '{{eve_secret:' + next(iter(first.values)) + '}}'
            failures = []
            def resolve_elsewhere():
                try: resolve_credentials(ref)
                except ValueError: failures.append(True)
            thread = threading.Thread(target=resolve_elsewhere); thread.start(); thread.join()
            self.assertEqual([True], failures)
            with credential_scope('Password: second-secret'):
                with self.assertRaises(ValueError): resolve_credentials(ref)
            self.assertEqual('one-secret', resolve_credentials(ref))

    def test_already_redacted_inputs_do_not_produce_usable_credentials(self):
        with credential_scope('Passwort: [REDACTED]\nSSID: Example') as scope:
            self.assertEqual({}, scope.values)
            self.assertEqual('', scope.contract())
