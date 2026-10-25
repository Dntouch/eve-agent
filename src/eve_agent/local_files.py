from __future__ import annotations

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import Callable


TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv",
    ".log", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".scss", ".xml", ".toml", ".ini", ".cfg", ".conf", ".sh", ".bash", ".zsh",
    ".sql", ".java", ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".rb", ".php",
}
RESOURCE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf",
}


class LocalFileAccessError(ValueError):
    pass


class LocalFileReader:
    """Read-only access beneath dynamically configured canonical roots."""

    def __init__(self, roots_provider: Callable[[], list[str]], *,
                 max_text_bytes: int = 2 * 1024 * 1024,
                 max_resource_bytes: int = 20 * 1024 * 1024):
        self.roots_provider = roots_provider
        self.max_text_bytes = max_text_bytes
        self.max_resource_bytes = max_resource_bytes

    def roots(self) -> tuple[Path, ...]:
        resolved = []
        for raw in self.roots_provider() or []:
            try:
                root = Path(str(raw)).expanduser().resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if root.is_dir() and root != Path(root.anchor) and root not in resolved:
                resolved.append(root)
        return tuple(resolved)

    def _require_roots(self) -> tuple[Path, ...]:
        roots = self.roots()
        if not roots:
            raise LocalFileAccessError("Es ist kein lesbarer lokaler Root freigegeben.")
        return roots

    def resolve(self, requested: str, *, directory: bool | None = None) -> Path:
        roots = self._require_roots()
        raw = str(requested or ".").strip()
        reference = re.fullmatch(r"root:(\d+)/(.*)", raw, re.S)
        if reference:
            index = int(reference.group(1))
            if index >= len(roots):
                raise LocalFileAccessError("Unbekannte oder nicht mehr freigegebene Root-Referenz.")
            candidates = [roots[index] / reference.group(2)]
        else:
            expanded = Path(raw).expanduser()
            candidates = [expanded] if expanded.is_absolute() else [root / expanded for root in roots]
        # Conversational follow-ups often contain only the filename that was
        # shown in the preceding search result. Resolve such a bare filename
        # only when it identifies exactly one safe file below the configured
        # roots; never guess between duplicates (including root-level files).
        if not reference and not Path(raw).is_absolute() and Path(raw).name == raw and directory is not True:
            matches = [path for path in self._walk_files() if path.name.casefold() == raw.casefold()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise LocalFileAccessError("Der Dateiname ist in den freigegebenen Roots nicht eindeutig.")
        for candidate in candidates:
            try:
                actual = candidate.resolve(strict=True)
            except (FileNotFoundError, OSError, RuntimeError):
                continue
            if not any(actual == root or actual.is_relative_to(root) for root in roots):
                continue
            if directory is True and not actual.is_dir():
                continue
            if directory is False and not actual.is_file():
                continue
            return actual
        # A model may preserve the correct filename from conversation history
        # while composing an incorrect relative/root directory. If the exact
        # path failed, recover only by an unambiguous basename inside a root.
        selector = Path(reference.group(2) if reference else raw)
        safe_relative = reference is not None or (
            not selector.is_absolute() and ".." not in selector.parts
        )
        if safe_relative and selector.name not in {"", ".", ".."} and directory is not True:
            matches = [path for path in self._walk_files() if path.name.casefold() == selector.name.casefold()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise LocalFileAccessError("Der Dateiname ist in den freigegebenen Roots nicht eindeutig.")
        raise LocalFileAccessError("Pfad fehlt, ist nicht lesbar oder liegt außerhalb der freigegebenen Roots.")

    def _reference(self, path: Path) -> str:
        for index, root in enumerate(self._require_roots()):
            if path == root or path.is_relative_to(root):
                relative = path.relative_to(root)
                return f"root:{index}/" + (str(relative) if str(relative) != "." else "")
        raise LocalFileAccessError("Pfad liegt außerhalb der freigegebenen Roots.")

    def list_directory(self, path: str = ".", *, limit: int | None = None) -> dict:
        directory = self.resolve(path, directory=True)
        entries = []
        try:
            children = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            raise LocalFileAccessError("Verzeichnis kann nicht gelesen werden.") from exc
        selected = children if limit is None else children[:max(int(limit), 1)]
        for child in selected:
            try:
                actual = child.resolve(strict=True)
                allowed = any(actual == root or actual.is_relative_to(root) for root in self.roots())
                if not allowed:
                    continue
                stat = actual.stat()
            except OSError:
                continue
            entries.append({"name": child.name, "path": self._reference(actual),
                            "kind": "directory" if actual.is_dir() else "file",
                            "size": stat.st_size if actual.is_file() else None})
        return {"directory": self._reference(directory), "entries": entries,
                "truncated": len(children) > len(entries)}

    def _walk_files(self):
        for root in self._require_roots():
            for base, directories, files in os.walk(root, followlinks=False):
                base_path = Path(base)
                directories[:] = [name for name in directories if self._safe_child(base_path / name)]
                for name in files:
                    path = base_path / name
                    if self._safe_child(path, file_only=True):
                        yield path.resolve(strict=True)

    def _safe_child(self, path: Path, *, file_only: bool = False) -> bool:
        try:
            actual = path.resolve(strict=True)
            allowed = any(actual == root or actual.is_relative_to(root) for root in self.roots())
            return allowed and (not file_only or actual.is_file())
        except (OSError, RuntimeError):
            return False

    def search_files(self, query: str, *, include_content: bool = True,
                     limit: int | None = None) -> list[dict]:
        terms = [term.casefold() for term in str(query).split() if term.strip()]
        if not terms:
            raise LocalFileAccessError("Die Dateisuche benötigt einen Suchtext.")
        matches = []
        for path in self._walk_files():
            label = str(path).casefold()
            name_score = sum(term in label for term in terms)
            content_score, excerpt = 0, ""
            if include_content and path.suffix.casefold() in TEXT_SUFFIXES and path.stat().st_size <= self.max_text_bytes:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
                folded = content.casefold()
                content_score = sum(term in folded for term in terms)
                if content_score:
                    first = min((folded.find(term) for term in terms if term in folded), default=0)
                    excerpt = content[max(0, first - 120):first + 380].replace("\x00", "")
            if name_score or content_score:
                matches.append({"path": self._reference(path), "name": path.name,
                                "size": path.stat().st_size, "excerpt": excerpt,
                                "score": name_score * 3 + content_score})
        matches.sort(key=lambda item: (-item["score"], item["path"].casefold()))
        return matches if limit is None else matches[:max(int(limit), 1)]

    def _readable_text(self, path: Path) -> str:
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            raise LocalFileAccessError("Dieser Dateityp wird nicht als Text interpretiert.")
        if path.stat().st_size > self.max_text_bytes:
            raise LocalFileAccessError("Die Textdatei ist für direktes Lesen zu groß; verwende die Textsuche.")
        try:
            return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
        except OSError as exc:
            raise LocalFileAccessError("Datei kann nicht gelesen werden.") from exc

    def read_text(self, path: str, *, start: int = 0, max_chars: int | None = None) -> dict:
        actual = self.resolve(path, directory=False)
        text = self._readable_text(actual)
        start = min(max(int(start), 0), len(text))
        maximum = len(text) - start if max_chars is None else max(int(max_chars), 1)
        return {"path": self._reference(actual), "content": text[start:start + maximum],
                "start": start, "next_start": start + maximum if start + maximum < len(text) else None,
                "total_chars": len(text)}

    def search_text(self, path: str, query: str, *, limit: int | None = None) -> dict:
        actual = self.resolve(path, directory=False)
        text = self._readable_text(actual)
        needle = str(query).casefold().strip()
        if not needle:
            raise LocalFileAccessError("Die Textsuche benötigt einen Suchtext.")
        lines = text.splitlines()
        hits = []
        for number, line in enumerate(lines, 1):
            if needle in line.casefold():
                hits.append({"line": number, "content": line})
                if limit is not None and len(hits) >= max(int(limit), 1):
                    break
        return {"path": self._reference(actual), "query": query, "matches": hits}

    def open_resource(self, path: str) -> dict:
        actual = self.resolve(path, directory=False)
        size = actual.stat().st_size
        if size > self.max_resource_bytes:
            raise LocalFileAccessError("Die Datei ist zu groß, um sie als Turn-Ressource zu öffnen.")
        media_type = RESOURCE_TYPES.get(actual.suffix.casefold())
        if media_type is None and actual.suffix.casefold() in TEXT_SUFFIXES:
            media_type = mimetypes.guess_type(actual.name)[0] or "text/plain"
        if media_type is None:
            raise LocalFileAccessError("Dieser Dateityp wird nicht als Turn-Ressource unterstützt.")
        try:
            body = actual.read_bytes()
        except OSError as exc:
            raise LocalFileAccessError("Datei kann nicht gelesen werden.") from exc
        return {"type": "image" if media_type.startswith("image/") else "attachment",
                "content": f"data:{media_type};base64," + base64.b64encode(body).decode(),
                "media_type": media_type, "filename": actual.name,
                "source": "local_file", "description": f"Lokale Datei {actual.name}",
                "path": self._reference(actual)}


class LocalFileCapability:
    def __init__(self, reader: LocalFileReader, llm):
        self.reader, self.llm = reader, llm

    def self_descriptions(self):
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "local_files.read", "local_files.read",
            "Ich kann freigegebene lokale Dateien suchen, lesen und als Ressource öffnen. "
            "Dieser Dateizugriff ist strikt read-only und kann Dateien weder verändern noch löschen.",
            "LocalFileCapability", "list_directory,search_files,read_text,search_text,open_resource",
        )]

    def minimal_contract(self) -> dict:
        return {
            "description": (
                "Nur lesender Zugriff auf freigegebene lokale Verzeichnisse. Ein Benutzer-Dateiname ist noch kein "
                "veröffentlichter Pfad: zuerst search_files mit dem exakten Namen, danach read_text mit dem dort "
                "gelieferten path; erst nach read_text aus dessen Inhalt antworten."
            ),
            "roots": [{"reference": f"root:{index}/", "name": root.name}
                      for index, root in enumerate(self.reader.roots())],
            "operations": {
                "list_directory": {"path": "string", "limit": "optional positive integer"},
                "search_files": {"query": "string", "include_content": "boolean", "limit": "integer"},
                "read_text": {"path": "exact path returned by search_files or list_directory",
                              "start": "integer", "max_chars": "integer"},
                "search_text": {"path": "published path", "query": "string", "limit": "integer"},
                "open_resource": {"path": "published path"},
            },
        }

    def execute_operation(self, operation: str, arguments: dict) -> dict:
        if not self.reader.roots():
            raise LocalFileAccessError("Es ist kein lokales Verzeichnis für EVE freigegeben.")
        if not isinstance(arguments, dict):
            raise LocalFileAccessError("Dateiargumente müssen ein Objekt sein.")
        if operation == "list_directory":
            result = self.reader.list_directory(str(arguments.get("path", ".")), limit=arguments.get("limit"))
        elif operation == "search_files":
            result = self.reader.search_files(str(arguments.get("query", "")),
                include_content=bool(arguments.get("include_content", True)), limit=arguments.get("limit"))
        elif operation == "read_text":
            result = self.reader.read_text(str(arguments.get("path", "")), start=arguments.get("start", 0),
                                           max_chars=arguments.get("max_chars"))
        elif operation == "search_text":
            result = self.reader.search_text(str(arguments.get("path", "")), str(arguments.get("query", "")),
                                              limit=arguments.get("limit"))
        elif operation == "open_resource":
            resource = self.reader.open_resource(str(arguments.get("path", "")))
            return {"answer": "Die angeforderte lokale Datei wurde als Turn-Ressource geöffnet.",
                    "resources": [resource], "result": {"path": resource["path"], "media_type": resource["media_type"]}}
        else:
            raise LocalFileAccessError("Nicht veröffentlichte Dateioperation.")
        return {"answer": "", "resources": [], "result": result}
