import unittest
from eve_agent.answer_stream import AnswerStreamMismatchError, unpublished_suffix
from eve_agent.memory import RedactedTextStream, redact_sensitive


class RedactedAnswerStreamTest(unittest.TestCase):
    def test_article_paths_and_long_identifiers_are_not_credentials(self):
        text = ('https://www.nrz.de/lokales/dinslaken-huenxe-voerde/article413335315/'
                'voerder-schule-wollte-jungen-mit-autismus-von-klassenfahrt-ausschliessen.html'
                '\nhttps://example.org/' + 'a' * 180 + '\n' + '1234abcd' * 8)
        self.assertEqual(text, redact_sensitive(text))

    def test_every_chunk_boundary_matches_storage(self):
        for credential in [
            'Authorization: Bearer private_credential_123456789',
            'Authorization:\nBasic\nprivate_credential_123456789',
            'Authorization:\nBearer\nprivate_credential_123456789',
            'api-key: "private credential with spaces"',
            'password\n=\nprivate_credential_123456789',
            'local\nkey: private_credential_123456789',
            'api\nkey = private_credential_123456789',
            'Bearer private_credential_123456789',
            'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature',
        ]:
            text = 'Vorher\n' + credential + '\nNachher'
            expected = redact_sensitive(text)
            self.assertNotEqual(text, expected)
            for boundary in range(len(text) + 1):
                with self.subTest(credential=credential, boundary=boundary):
                    chunks = []
                    stream = RedactedTextStream(chunks.append)
                    stream.feed(text[:boundary])
                    stream.feed(text[boundary:])
                    stream.finish()
                    self.assertEqual(expected, ''.join(chunks))
                    self.assertEqual('', unpublished_suffix(chunks, expected))
            chunks = []
            stream = RedactedTextStream(chunks.append)
            for character in text:
                stream.feed(character)
            stream.finish()
            self.assertEqual(expected, ''.join(chunks))

    def test_reset_and_unbounded_line(self):
        chunks = []
        stream = RedactedTextStream(chunks.append)
        stream.feed('password=discarded')
        stream.reset()
        text = 'x' * 100000
        stream.feed(text)
        self.assertEqual([], chunks)
        stream.finish()
        stream.finish()
        self.assertEqual([text], chunks)

    def test_real_mismatch_is_still_rejected(self):
        with self.assertRaises(AnswerStreamMismatchError):
            unpublished_suffix(['Antwort A'], 'Antwort B')
