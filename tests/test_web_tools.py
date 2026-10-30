import json
import io
import unittest
from unittest import mock
import urllib.parse
import urllib.error

from eve_agent.web_tools import (
    WebResearch,
    WebNoResults,
    WebReadError,
    _assert_public_url,
    _TextExtractor,
    _is_http_source,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.stream = io.BytesIO(payload)

    def __enter__(self):
        self.stream.seek(0)
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.stream.read(limit)


class FakeHeaders:
    def get_content_type(self): return "text/html"
    def get_content_charset(self): return "utf-8"


class WebToolTest(unittest.TestCase):

    @staticmethod
    def pdf_bytes(texts=('First page evidence', 'Second page evidence'), *, password=None):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        writer.add_metadata({'/Title': 'PDF test document'})
        for text in texts:
            page = writer.add_blank_page(width=200, height=200)
            if text:
                font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                    NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
                page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
                    DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
                stream = DecodedStreamObject()
                stream.set_data(f'BT /F1 12 Tf 20 100 Td ({text}) Tj ET'.encode())
                page[NameObject('/Contents')] = writer._add_object(stream)
        if password:
            writer.encrypt(password)
        output = io.BytesIO(); writer.write(output)
        return output.getvalue()

    def pdf_response(self, payload, mime='application/pdf'):
        response = FakeResponse(payload)
        response.headers = mock.Mock()
        response.headers.get_content_type.return_value = mime
        response.headers.get_content_charset.return_value = None
        opener = mock.Mock(); opener.open.return_value = response
        return opener

    def test_pdf_url_is_read_with_page_numbers_using_existing_url_operation(self):
        research = WebResearch({})
        opener = self.pdf_response(self.pdf_bytes())
        url = 'https://example.org/download?id=123'
        with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
            result = research.execute_native_operation('read_urls', {'urls': [url]})
        self.assertIn('[Seite 1]', result['context'])
        self.assertIn('First page evidence', result['context'])
        self.assertIn('[Seite 2]', result['context'])
        self.assertIn('Second page evidence', result['context'])
        self.assertEqual(url, result['sources'][0]['url'])
        opener.open.assert_called_once()

    def test_pdf_signature_handles_generic_download_content_type(self):
        opener = self.pdf_response(self.pdf_bytes(), mime='application/octet-stream')
        with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
            result = WebResearch({}).execute_native_operation('read_pdf',
                {'url': 'https://example.org/download', 'pages': [2, 2]})
        self.assertEqual(2, result['page_count'])
        self.assertEqual([{'page': 2, 'text': 'Second page evidence'}], result['pages'])
        self.assertEqual('PDF test document', result['title'])
        self.assertFalse(result['all_pages_selected'])
        self.assertNotIn('First page evidence', result['context'])
        self.assertFalse(result['ocr_performed'])

    def test_blank_pdf_pages_are_reported_without_fabricated_text(self):
        raw = self.pdf_bytes(('', 'Actual text'))
        result = WebResearch._pdf_text(raw)
        self.assertEqual([1], result['empty_text_pages'])
        self.assertEqual('', result['pages'][0]['text'])
        self.assertIn('Actual text', WebResearch._pdf_context(result))
        opener = self.pdf_response(self.pdf_bytes(('',)))
        with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(WebReadError, 'OCR'):
                WebResearch({}).read_urls(['https://example.org/scan.pdf'])

    def test_invalid_pdf_pages_and_password_protection_are_explicit_errors(self):
        raw = self.pdf_bytes()
        for pages in ([], [0], [True], [3], '2'):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                WebResearch._pdf_text(raw, pages=pages)
        with self.assertRaisesRegex(ValueError, 'passwortgeschützt'):
            WebResearch._pdf_text(self.pdf_bytes(password='test-password'))

    def test_corrupt_pdf_and_non_pdf_response_are_not_reported_as_readable(self):
        with self.assertRaisesRegex(ValueError, 'PDF konnte nicht gelesen'):
            WebResearch._pdf_text(b'%PDF-1.7\ninvalid')
        opener = self.pdf_response(b'<p>not a PDF</p>', mime='text/html')
        with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'kein PDF'):
                WebResearch({}).execute_native_operation('read_pdf', {'url': 'https://example.org/file.pdf'})

    def test_pdf_fetch_keeps_existing_public_url_and_download_size_checks(self):
        with mock.patch('eve_agent.web_tools.socket.getaddrinfo',
                return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
            with self.assertRaisesRegex(ValueError, 'Lokale Netzwerkziele'):
                WebResearch({}).execute_native_operation('read_pdf', {'url': 'http://example.test/file.pdf'})
        opener = self.pdf_response(self.pdf_bytes())
        with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, '100 Bytes'):
                WebResearch({'max_pdf_bytes': 100}).read_page('https://example.org/file.pdf')

    def test_pdf_larger_than_old_limit_is_read_via_both_operations_and_mime_detection(self):
        raw = self.pdf_bytes() + b'\n%' + b'x' * 6_000_000
        for mime in ('application/pdf', 'application/octet-stream'):
            for operation, parameters in (
                ('read_pdf', {'url': 'https://example.org/download', 'pages': [2]}),
                ('read_urls', {'urls': ['https://example.org/download']}),
            ):
                with self.subTest(mime=mime, operation=operation):
                    opener = self.pdf_response(raw, mime=mime)
                    with mock.patch('eve_agent.web_tools._assert_public_url'), mock.patch(
                            'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
                        result = WebResearch({}).execute_native_operation(operation, parameters)
                    self.assertIn('Second page evidence', result['context'])

    def test_pdf_limit_accepts_exact_size_and_rejects_one_byte_over(self):
        raw = self.pdf_bytes()
        for mime in ('application/pdf', 'application/octet-stream'):
            for limit in (len(raw), len(raw) - 1):
                opener = self.pdf_response(raw, mime=mime)
                response = opener.open.return_value
                response.read = mock.Mock(wraps=response.read)
                with self.subTest(mime=mime, limit=limit), mock.patch(
                        'eve_agent.web_tools._assert_public_url'), mock.patch(
                        'eve_agent.web_tools.urllib.request.build_opener', return_value=opener):
                    research = WebResearch({'max_pdf_bytes': limit})
                    if limit == len(raw):
                        self.assertIn('First page evidence', research.read_page('https://example.org/download'))
                    else:
                        with self.assertRaisesRegex(RuntimeError, f'Das PDF.*{limit} Bytes'):
                            research.read_page('https://example.org/download')
                self.assertEqual(limit + 1, sum(call.args[0] for call in response.read.call_args_list))

    def test_text_extractor_omits_page_chrome_and_keeps_article_content(self):
        parser = _TextExtractor()
        parser.feed(
            '<header>Seitentitel</header><nav>Menü Inland Ausland</nav>'
            '<main><article><h1>Aktuelle Meldung</h1><p>Belegter Inhalt.</p></article></main>'
            '<aside>Werbung</aside><footer>Impressum</footer>'
        )
        text = parser.text()
        self.assertIn('Aktuelle Meldung', text)
        self.assertIn('Belegter Inhalt.', text)
        self.assertNotIn('Menü', text)
        self.assertNotIn('Werbung', text)
        self.assertNotIn('Impressum', text)




    def test_direct_url_reader_combines_pages_without_search(self):
        research = WebResearch({"page_chars": 100})
        with mock.patch.object(research, "read_page", side_effect=["Erster Inhalt", "Zweiter Inhalt"]):
            context, sources = research.read_urls(["https://example.org/a", "https://example.net/b"])
        self.assertIn("Erster Inhalt", context)
        self.assertIn("Zweiter Inhalt", context)
        self.assertEqual(["https://example.org/a", "https://example.net/b"], [item["url"] for item in sources])

    def test_search_returns_all_backend_snippets_and_preserves_source_order(self):
        research = WebResearch({})
        sources = [
            {"title": "Eins", "url": "https://example.org/one", "snippet": "s1"},
            {"title": "Zwei", "url": "https://example.net/two", "snippet": "s2"},
        ]
        with mock.patch.object(research, "_search_sources", return_value=sources), mock.patch.object(
            research, "read_page",
        ) as read_page:
            context, published = research.research("test")

        self.assertLess(context.index("[1] Eins"), context.index("[2] Zwei"))
        self.assertIn("s1", context)
        self.assertIn("s2", context)
        self.assertEqual(sources, published)
        read_page.assert_not_called()


    def test_only_http_sources_can_be_rendered_as_links(self):
        self.assertTrue(_is_http_source("https://example.org/info"))
        self.assertTrue(_is_http_source("http://example.org/info"))
        self.assertFalse(_is_http_source("javascript:alert(1)"))
        self.assertFalse(_is_http_source("data:text/html,boom"))
        self.assertFalse(_is_http_source("/relative"))

    def test_page_reader_blocks_private_loopback_and_link_local_targets(self):
        for address in ("127.0.0.1", "192.168.2.10", "169.254.169.254"):
            with self.subTest(address=address), mock.patch(
                "eve_agent.web_tools.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", (address, 80))],
            ):
                with self.assertRaisesRegex(ValueError, "Lokale Netzwerkziele"):
                    _assert_public_url("http://example.test/private")

    def test_search_backend_cannot_inject_active_source_links(self):
        payload = json.dumps({"results": [
            {"title": "Böse", "url": "javascript:alert(1)", "content": "x"},
            {"title": "Gut", "url": "https://example.org/info", "content": "ok"},
        ]}).encode()
        research = WebResearch({"read_pages": 0})
        with mock.patch("eve_agent.web_tools.urllib.request.urlopen", return_value=FakeResponse(payload)):
            _, sources = research.research("test")
        self.assertEqual(["https://example.org/info"], [source["url"] for source in sources])

    def test_oversized_search_response_is_rejected(self):
        research = WebResearch({"read_pages": 0})
        with mock.patch(
            "eve_agent.web_tools.urllib.request.urlopen",
            return_value=FakeResponse(b"x" * 2_000_001),
        ):
            with self.assertRaisesRegex(RuntimeError, "große Antwort"):
                research.research("test")

    def test_oversized_page_is_rejected_instead_of_silently_truncated(self):
        research = WebResearch({})
        response = FakeResponse(b"x" * (research.max_page_bytes + 1))
        response.read = mock.Mock(wraps=response.read)
        response.headers = FakeHeaders()
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("eve_agent.web_tools._assert_public_url"), mock.patch(
            "eve_agent.web_tools.urllib.request.build_opener", return_value=opener,
        ):
            with self.assertRaisesRegex(RuntimeError, "5000000"):
                research.read_page("https://example.org/large")
        self.assertEqual([mock.call(1024), mock.call(5_000_001 - 1024)], response.read.call_args_list)

    def test_large_html_is_fully_read_and_scripts_are_removed(self):
        response = FakeResponse(b'<script>' + b'x' * 800_000 + b'</script><p>Wetterbericht</p>')
        response.headers = FakeHeaders()
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("eve_agent.web_tools._assert_public_url"), mock.patch(
            "eve_agent.web_tools.urllib.request.build_opener", return_value=opener,
        ):
            self.assertEqual("Wetterbericht", WebResearch({}).read_page("https://example.org/large"))
            with self.assertRaisesRegex(RuntimeError, "750000"):
                WebResearch({"max_page_bytes": 750_000}).read_page("https://example.org/large")

    def test_failed_urls_keep_individual_http_statuses_in_runtime_error(self):
        research = WebResearch({})
        urls = ["https://example.org/blocked", "https://example.org/missing"]
        errors = [urllib.error.HTTPError(url, status, reason, {}, None)
                  for url, status, reason in zip(urls, [403, 404], ["Forbidden", "Not Found"])]
        with mock.patch.object(research, "read_page", side_effect=errors):
            with self.assertRaises(WebReadError) as caught:
                research.execute_native_operation("read_urls", {"urls": urls})
        failures = caught.exception.structure["url_errors"]
        self.assertEqual([403, 404], [item["http_status"] for item in failures])
        self.assertEqual(urls, [item["url"] for item in failures])
        self.assertIn("403", str(caught.exception))
        self.assertIn("404", str(caught.exception))

    def test_partial_success_preserves_source_and_reports_failed_url_without_retry(self):
        research = WebResearch({})
        good, bad = "https://example.org/good", "https://example.org/bad"
        with mock.patch.object(research, "read_page", side_effect=["Inhalt", TimeoutError("timed out")]) as read:
            result = research.execute_native_operation("read_urls", {"urls": [good, bad, good]})
        self.assertEqual(2, read.call_count)
        self.assertEqual([good], [source["url"] for source in result["sources"]])
        self.assertEqual("TimeoutError", result["url_errors"][0]["error_class"])
        self.assertIn(bad, result["context"])
        self.assertIn("Inhalt", result["context"])

    def test_empty_page_is_reported_as_failure(self):
        response = FakeResponse(b"<script>only scripts</script>")
        response.headers = FakeHeaders()
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("eve_agent.web_tools._assert_public_url"), mock.patch(
            "eve_agent.web_tools.urllib.request.build_opener", return_value=opener,
        ):
            with self.assertRaisesRegex(WebReadError, "keinen lesbaren Text"):
                WebResearch({}).read_urls(["https://example.org/empty"])

    def test_empty_successful_search_has_distinct_no_results_outcome(self):
        payload = json.dumps({"results": []}).encode()
        research = WebResearch({"read_pages": 0})
        with mock.patch("eve_agent.web_tools.urllib.request.urlopen", return_value=FakeResponse(payload)):
            with self.assertRaisesRegex(WebNoResults, "keine Ergebnisse"):
                research.research("DiCUNO E14 LED 3W Kühlschranklampe Amazon")

    def test_site_scoped_search_variants_are_deduplicated(self):
        first = json.dumps({"results": [
            {"title": "Produkt", "url": "https://shop.example/product", "content": "Exakter Treffer"},
        ]}).encode()
        second = json.dumps({"results": [
            {"title": "Produkt doppelt", "url": "https://shop.example/product", "content": "Doppelt"},
            {"title": "Alternative", "url": "https://shop.example/alternative", "content": "Alternative"},
        ]}).encode()
        research = WebResearch({"read_pages": 0, "results": 5})
        with mock.patch(
            "eve_agent.web_tools.urllib.request.urlopen",
            side_effect=[FakeResponse(first), FakeResponse(second)],
        ) as urlopen:
            result = research.execute_operation({
                "type": "search",
                "queries": ["DiCUNO E14 LED 3W", "DiCUNO Kühlschranklampe"],
                "site": "shop.example",
            })

        self.assertEqual(2, urlopen.call_count)
        requested = [urllib.parse.unquote(call.args[0].full_url) for call in urlopen.call_args_list]
        self.assertTrue(all("site:shop.example" in url for url in requested))
        self.assertEqual(
            ["https://shop.example/product", "https://shop.example/alternative"],
            [source["url"] for source in result["sources"]],
        )
        self.assertEqual("shop.example", result["site"])
        self.assertEqual(2, len(result["queries"]))

    def test_all_site_scoped_variants_without_results_preserve_no_results(self):
        empty = json.dumps({"results": []}).encode()
        research = WebResearch({"read_pages": 0})
        with mock.patch(
            "eve_agent.web_tools.urllib.request.urlopen",
            side_effect=[FakeResponse(empty), FakeResponse(empty)],
        ) as urlopen:
            with self.assertRaises(WebNoResults):
                research.execute_operation({
                    "type": "search", "queries": ["exakt", "breiter"], "site": "example.org",
                })
        self.assertEqual(2, urlopen.call_count)

    def test_search_variants_are_unbounded_but_site_and_shape_are_validated(self):
        research = WebResearch({})
        invalid = (
            {"type": "search", "query": "eins", "queries": ["zwei"]},
            {"type": "search", "query": "eins", "site": "https://example.org/path"},
        )
        for operation in invalid:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                research.execute_operation(operation)
        many = [str(index) for index in range(10)]
        with mock.patch.object(research, "_search_sources", return_value=[]):
            with self.assertRaises(WebNoResults):
                research.execute_operation({"type": "search", "queries": many})

    def test_provider_publishes_generic_image_search_operation(self):
        research = WebResearch({})
        context = research.native_contract()
        operations = set(context["operations"])
        self.assertEqual({"search", "read_urls", "read_pdf", "search_images"}, operations)
        self.assertIn("search_images", context["operations"])

    def test_image_search_returns_generic_resources_and_skips_broken_results(self):
        payload = json.dumps({"results": [
            {"title": "Defekt", "img_src": "https://img.example/bad.jpg", "url": "https://page.example/bad"},
            {"title": "Eins", "img_src": "https://img.example/one.png", "url": "https://page.example/one"},
            {"title": "Zwei", "img_src": "https://img.example/two.jpg", "url": "https://page.example/two"},
        ]}).encode()
        research = WebResearch({"image_results": 2})
        with mock.patch("eve_agent.web_tools.urllib.request.urlopen", return_value=FakeResponse(payload)), mock.patch.object(
            research, "_read_image", side_effect=[ValueError("broken"), ("image/png", b"png"), ("image/jpeg", b"jpg")],
        ):
            result = research.search_images("beliebiges Thema")

        self.assertEqual("search_images", result["operation"])
        self.assertEqual(2, len(result["resources"]))
        self.assertTrue(result["resources"][0]["content"].startswith("data:image/png;base64,"))
        self.assertEqual("https://page.example/one", result["resources"][0]["source"]["url"])
        self.assertEqual("image/png", result["resources"][0]["metadata"]["mime_type"])


if __name__ == "__main__": unittest.main()
