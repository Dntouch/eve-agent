from __future__ import annotations
import base64
import html
import ipaddress
import io
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


class WebNoResults(RuntimeError):
    """The search backend answered successfully but returned no usable results."""


class WebReadError(RuntimeError):
    """Preserve per-URL failures, including in the native runtime's error envelope."""

    def __init__(self, failures: list[dict]):
        self.structure = {"url_errors": failures}
        details = "; ".join(f"{item['url']}: {item['message']}" for item in failures)
        super().__init__(f"Die angegebenen Webseiten konnten nicht gelesen werden: {details}")


class _TextExtractor(HTMLParser):
    HIDDEN_TAGS = {
        "script", "style", "svg", "noscript", "template",
        "nav", "header", "footer", "aside", "form",
    }

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN_TAGS:
            self.hidden += 1
        elif tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.HIDDEN_TAGS and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        text = html.unescape(" ".join(self.parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        return re.sub(r"\n\s*\n+", "\n", text).strip()


def _assert_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Nicht unterstützte URL")
    for result in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(result[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Lokale Netzwerkziele werden nicht gelesen")


def _is_http_source(url: str) -> bool:
    """Only render ordinary web links returned by the search backend."""

    try:
        parsed = urllib.parse.urlparse(url)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebResearch:
    def __init__(self, config: dict):
        self.search_url = config.get("searxng_url", "http://127.0.0.1:8888").rstrip("/")
        self.timeout = int(config.get("timeout_seconds", 12))
        self.image_results = min(max(int(config.get("image_results", 4)), 1), 8)
        self.max_image_bytes = 5 * 1024 * 1024
        self.max_page_bytes = int(config.get("max_page_bytes", 5_000_000))
        self.max_pdf_bytes = int(config.get("max_pdf_bytes", 50 * 1024 * 1024))

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "web.research", "web.research",
            "Ich kann das Web durchsuchen, öffentliche Webseiten und PDF-Texte lesen und öffentliche Bilder beschaffen.",
            "WebResearch", "search,read_urls,read_pdf,search_images",
        )]

    @staticmethod
    def native_contract() -> dict:
        """Publish the operations implemented by this provider itself."""
        return {
            "description": (
                "Search public web sources, read supplied public URLs including PDF documents, or fetch public image results."
            ),
            "operations": {
                "search": {
                    "effect": "read",
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "queries": {
                                "type": "array", "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "site": {
                                "type": "string",
                                "pattern": (
                                    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}"
                                    r"[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
                                ),
                            },
                        },
                        "oneOf": [
                            {"required": ["query"], "not": {"required": ["queries"]}},
                            {"required": ["queries"], "not": {"required": ["query"]}},
                        ],
                    },
                },
                "read_urls": {
                    "effect": "read",
                    "description": "Read public HTML, text or PDF URLs. PDF text includes page numbers; image-only scans have no extractable text.",
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "urls": {
                                "type": "array", "minItems": 1,
                                "items": {"type": "string", "format": "uri"},
                            },
                        },
                        "required": ["urls"],
                    },
                },
                "read_pdf": {
                    "effect": "read",
                    "description": "Read text from a public PDF URL, optionally selecting exact one-based page numbers. Returns page count, page texts, empty-page information and source URL. Does not perform OCR.",
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "url": {"type": "string", "format": "uri"},
                            "pages": {"type": "array", "minItems": 1,
                                      "items": {"type": "integer", "minimum": 1}},
                        },
                        "required": ["url"],
                    },
                },
                "search_images": {
                    "effect": "read",
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"query": {"type": "string", "minLength": 1}},
                        "required": ["query"],
                    },
                },
            },
        }

    def execute_native_operation(self, operation: str, parameters: dict) -> dict:
        if operation not in self.native_contract()["operations"]:
            raise ValueError("Nicht veröffentlichte Web-Provider-Operation")
        if not isinstance(parameters, dict):
            raise ValueError("Ungültiger Web-Provider-Aufruf")
        return self.execute_operation({"type": operation, **parameters})

    def execute_operation(self, operation: dict) -> dict:
        if not isinstance(operation, dict):
            raise ValueError("Ungültiger Web-Provider-Aufruf")
        kind = operation.get("type")
        if kind == "search":
            query = operation.get("query")
            queries = operation.get("queries")
            if query is not None and queries is not None:
                raise ValueError("Websuche akzeptiert query oder queries, nicht beides")
            if query is not None:
                queries = [query]
            if (
                not isinstance(queries, list) or not queries
                or any(not isinstance(item, str) or not item.strip() for item in queries)
            ):
                raise ValueError("Websuche benötigt mindestens eine Suchanfrage")
            site = operation.get("site")
            normalized_site = self._normalize_search_site(site) if site is not None else None
            clean_queries = [item.strip() for item in queries]
            context, sources = self.research_many(clean_queries, site=normalized_site)
            effective_queries = [
                f"site:{normalized_site} {item}" if normalized_site else item for item in clean_queries
            ]
            return {
                "operation": kind,
                "query": " | ".join(effective_queries),
                "queries": effective_queries,
                "site": normalized_site,
                "context": context,
                "sources": sources,
                "resources": [],
            }
        if kind == "read_urls":
            urls = operation.get("urls")
            if not isinstance(urls, list) or not urls or any(not isinstance(url, str) or not url.strip() for url in urls):
                raise ValueError("Seitenabruf benötigt urls")
            context, sources, failures = self._read_urls(urls)
            return {"operation": kind, "context": context, "sources": sources,
                    "resources": [], "url_errors": failures}
        if kind == 'read_pdf':
            url = operation.get('url')
            if not isinstance(url, str) or not url.strip():
                raise ValueError('PDF-Abruf benötigt eine URL')
            content_type, raw, _ = self._read_document(url)
            if content_type != 'application/pdf' and not raw.lstrip().startswith(b'%PDF-'):
                raise ValueError('Die URL liefert kein PDF-Dokument')
            result = self._pdf_text(raw, pages=operation.get('pages'))
            context = self._pdf_context(result)
            return {**result, 'operation': kind, 'url': url, 'context': context,
                    'sources': [{'title': result['title'] or urllib.parse.urlparse(url).hostname or url,
                                 'url': url, 'snippet': context}], 'resources': []}
        if kind == "search_images":
            query = operation.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Bildsuche benötigt query")
            return self.search_images(query)
        raise ValueError("Nicht veröffentlichte Web-Provider-Operation")

    def research(self, query: str) -> tuple[str, list[dict[str, str]]]:
        return self.research_many([query])

    @staticmethod
    def _normalize_search_site(site: str) -> str:
        if not isinstance(site, str):
            raise ValueError("Websitebezug muss ein Hostname sein")
        candidate = site.strip().lower().rstrip(".")
        if "://" in candidate:
            parsed = urllib.parse.urlparse(candidate)
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                raise ValueError("Websitebezug darf keinen Pfad enthalten")
            candidate = parsed.hostname or ""
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", candidate):
            raise ValueError("Websitebezug muss ein gültiger öffentlicher Hostname sein")
        return candidate

    def _search_sources(self, query: str) -> list[dict[str, str]]:
        params = urllib.parse.urlencode({"q": query, "format": "json", "language": "de-DE", "safesearch": 0})
        request = urllib.request.Request(f"{self.search_url}/search?{params}", headers={"User-Agent": "EVE-Local-Agent/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw_payload = response.read(2_000_001)
        if len(raw_payload) > 2_000_000:
            raise RuntimeError("Die Websuche hat eine unerwartet große Antwort geliefert")
        payload = json.loads(raw_payload)
        raw = payload.get("results", [])
        sources = [
            {"title": str(item.get("title") or item.get("url") or "Quelle"), "url": str(item.get("url") or ""), "snippet": str(item.get("content") or "")}
            for item in raw if _is_http_source(str(item.get("url") or ""))
        ]
        return sources

    def research_many(self, queries: list[str], *, site: str | None = None) -> tuple[str, list[dict[str, str]]]:
        if not queries:
            raise ValueError("Websuche benötigt mindestens eine Suchanfrage")
        normalized_site = self._normalize_search_site(site) if site else None
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for query in queries:
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Leere Suchanfrage")
            effective_query = f"site:{normalized_site} {query.strip()}" if normalized_site else query.strip()
            for source in self._search_sources(effective_query):
                if source["url"] in seen_urls:
                    continue
                seen_urls.add(source["url"])
                sources.append(source)
        sections = []
        for number, source in enumerate(sources, 1):
            excerpt = source["snippet"]
            sections.append(f"[{number}] {source['title']}\nURL: {source['url']}\n{excerpt}")
        if not sections:
            raise WebNoResults("Die Websuche hat keine Ergebnisse geliefert")
        return "\n\n".join(sections), sources

    def _read_document(self, url: str) -> tuple[str, bytes, str]:
        _assert_public_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EVE Local Agent)"})
        with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=self.timeout) as response:
            content_type = response.headers.get_content_type()
            # Sniff the body too: download endpoints often label PDFs as binary.
            prefix = response.read(min(1024, self.max_page_bytes + 1, self.max_pdf_bytes + 1))
            is_pdf = content_type == "application/pdf" or prefix.lstrip().startswith(b"%PDF-")
            limit = self.max_pdf_bytes if is_pdf else self.max_page_bytes
            raw = prefix + response.read(max(0, limit + 1 - len(prefix)))
            if len(raw) > limit:
                kind = "Das PDF" if is_pdf else "Die Webseite"
                raise RuntimeError(
                    f"{kind} überschreitet die technische Abrufgröße von {limit} Bytes"
                )
            charset = response.headers.get_content_charset() or "utf-8"
        return content_type, raw, charset

    @staticmethod
    def _pdf_text(raw: bytes, *, pages=None) -> dict:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
        if pages is not None and (not isinstance(pages, list) or not pages
                or any(type(page) is not int or page < 1 for page in pages)):
            raise ValueError('pages muss positive, bei 1 beginnende Seitenzahlen enthalten')
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted and not reader.decrypt(''):
                raise ValueError('Das PDF ist passwortgeschützt und kann ohne Passwort nicht gelesen werden')
            count = len(reader.pages)
            selected = list(dict.fromkeys(pages)) if pages is not None else list(range(1, count + 1))
            if any(page > count for page in selected):
                raise ValueError(f'Das PDF hat {count} Seiten; eine angeforderte Seite liegt außerhalb des Dokuments')
            extracted = [{'page': number, 'text': (reader.pages[number - 1].extract_text() or '').strip()}
                         for number in selected]
            metadata = reader.metadata
            title = str(metadata.title or '') if metadata else ''
        except PyPdfError as exc:
            raise ValueError(f'Das PDF konnte nicht gelesen werden: {exc}') from exc
        return {'title': title, 'page_count': count, 'pages': extracted,
                'empty_text_pages': [page['page'] for page in extracted if not page['text']],
                'all_pages_selected': len(selected) == count,
                'has_extractable_text': any(page['text'] for page in extracted),
                'ocr_performed': False}

    @staticmethod
    def _pdf_context(result: dict) -> str:
        sections = [f"PDF · {result['page_count']} Seiten"]
        for page in result['pages']:
            sections.append(f"[Seite {page['page']}]\n" + (page['text'] or
                '[Kein auslesbarer Text auf dieser Seite; Bild-/Scaninhalt wird nicht per OCR gelesen.]'))
        return '\n\n'.join(sections)

    def read_page(self, url: str) -> str:
        content_type, raw, charset = self._read_document(url)
        if content_type == 'application/pdf' or raw.lstrip().startswith(b'%PDF-'):
            result = self._pdf_text(raw)
            if not any(page['text'] for page in result['pages']):
                raise ValueError('Das PDF enthält keinen auslesbaren Text; Bild-/Scanseiten benötigen OCR')
            return self._pdf_context(result)
        if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise ValueError("Kein lesbares Textdokument")
        text = raw.decode(charset, errors="replace")
        if content_type == "text/plain":
            text = text.strip()
        else:
            parser = _TextExtractor(); parser.feed(text)
            text = parser.text()
        if not text:
            raise ValueError("Die Webseite enthält keinen lesbaren Text")
        return text

    def read_urls(self, urls: list[str]) -> tuple[str, list[dict[str, str]]]:
        """Read user-supplied public pages without routing them through search."""
        context, sources, _ = self._read_urls(urls)
        return context, sources

    def _read_urls(self, urls: list[str]) -> tuple[str, list[dict[str, str]], list[dict]]:
        unique = list(dict.fromkeys(urls))
        if not unique:
            raise ValueError("Keine URL angegeben")
        sections, sources = [], []
        failures = []
        for url in unique:
            try:
                page = self.read_page(url)
            except (OSError, RuntimeError, ValueError, LookupError) as exc:
                failure = {"url": url, "error_class": type(exc).__name__, "message": str(exc)}
                if isinstance(exc, urllib.error.HTTPError):
                    failure["http_status"] = exc.code
                    exc.close()
                failures.append(failure)
                continue
            parsed = urllib.parse.urlparse(url)
            title = parsed.hostname or url
            sources.append({"title": title, "url": url, "snippet": page})
            sections.append(f"[{len(sources)}] {title}\nURL: {url}\n{page}")
        if not sections:
            raise WebReadError(failures)
        if failures:
            sections.append("Nicht gelesene URLs:\n" + "\n".join(
                f"{item['url']}: {item['message']}" for item in failures
            ))
        return "\n\n".join(sections), sources, failures

    def search_images(self, query: str) -> dict:
        """Fetch bounded, untrusted image results without semantic ranking."""
        params = urllib.parse.urlencode({
            "q": query, "format": "json", "language": "de-DE",
            "safesearch": 0, "categories": "images",
        })
        request = urllib.request.Request(
            f"{self.search_url}/search?{params}", headers={"User-Agent": "EVE-Local-Agent/0.1"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw_payload = response.read(2_000_001)
        if len(raw_payload) > 2_000_000:
            raise RuntimeError("Die Bildsuche hat eine unerwartet große Antwort geliefert")
        payload = json.loads(raw_payload)
        resources, sources = [], []
        for item in payload.get("results", []):
            if len(resources) >= self.image_results:
                break
            image_url = str(item.get("img_src") or item.get("thumbnail_src") or "")
            page_url = str(item.get("url") or "")
            if not _is_http_source(image_url):
                continue
            try:
                mime, content = self._read_image(image_url)
            except (OSError, RuntimeError, ValueError):
                continue
            title = str(item.get("title") or "Bild")
            source = {"title": title, "url": page_url if _is_http_source(page_url) else image_url}
            sources.append(source)
            resources.append({
                "type": "image",
                "content": f"data:{mime};base64," + base64.b64encode(content).decode("ascii"),
                "source": source,
                "metadata": {"mime_type": mime, "image_url": image_url},
            })
        if not resources:
            raise RuntimeError("Die Bildsuche hat keine verwendbaren Bilder geliefert")
        context = "\n".join(
            f"[{index}] {source['title']}\nUrsprungsseite: {source['url']}"
            for index, source in enumerate(sources, 1)
        )
        return {"operation": "search_images", "query": query, "context": context,
                "sources": sources, "resources": resources}

    def _read_image(self, url: str) -> tuple[str, bytes]:
        _assert_public_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EVE Local Agent)"})
        with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=self.timeout) as response:
            mime = response.headers.get_content_type().casefold()
            signatures = {
                "image/gif": (b"GIF87a", b"GIF89a"),
                "image/jpeg": (b"\xff\xd8\xff",),
                "image/png": (b"\x89PNG\r\n\x1a\n",),
                "image/webp": (b"RIFF",),
            }.get(mime)
            if signatures is None:
                raise ValueError("Nicht unterstütztes Bildformat")
            content = response.read(self.max_image_bytes + 1)
        if not content or len(content) > self.max_image_bytes:
            raise ValueError("Bild ist leer oder zu groß")
        valid = content.startswith(signatures)
        if mime == "image/webp":
            valid = content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        if not valid:
            raise ValueError("Bilddaten passen nicht zum MIME-Type")
        return mime, content
