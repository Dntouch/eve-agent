from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path


FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
EXTENSIONS = {
    "python": ".py", "py": ".py", "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts", "bash": ".sh", "sh": ".sh",
    "powershell": ".ps1", "html": ".html", "css": ".css", "json": ".json",
    "yaml": ".yaml", "yml": ".yml", "sql": ".sql", "markdown": ".md",
    "md": ".md", "text": ".txt", "txt": ".txt",
}


def output_resources(resources, artifacts=()) -> list[dict]:
    """Normalize inline response attachments without resolving paths or URLs."""
    outputs, seen = [], set()
    candidates = list(resources)
    for artifact in artifacts:
        if isinstance(artifact, dict) and isinstance(artifact.get("base64"), str):
            candidates.append({
                "type": "file", "filename": artifact.get("filename") or "eve-download.bin",
                "media_type": artifact.get("mime") or "application/octet-stream",
                "content": f"data:{artifact.get('mime') or 'application/octet-stream'};base64,{artifact['base64']}",
            })
    for resource in candidates:
        if not isinstance(resource, dict):
            continue
        kind, content = resource.get("type"), resource.get("content")
        if kind not in {"image", "file", "attachment"} or not isinstance(content, str):
            continue
        if not content.startswith("data:image/" if kind == "image" else "data:"):
            continue
        clean = {key: resource[key] for key in ("content", "filename", "media_type") if key in resource}
        clean["type"] = "image" if kind == "image" else "file"
        identity = (clean["type"], content, clean.get("filename") or "eve-download.bin")
        if identity not in seen:
            outputs.append(clean)
            seen.add(identity)
    return outputs


def extract_artifacts(answer: str, request: str = "") -> tuple[str, list[dict[str, str]]]:
    matches = list(FENCE.finditer(answer))
    if not matches:
        return answer.strip(), []
    requested_name = _requested_filename(request)
    artifacts = []
    spoken_parts = []
    cursor = 0
    for number, match in enumerate(matches, 1):
        info, content = match.group(1).strip(), match.group(2).rstrip() + "\n"
        language = info.split()[0].lower() if info else "text"
        explicit_filename = _filename(info)
        filename = explicit_filename or (requested_name if number == 1 else None)
        spoken_parts.append(answer[cursor:match.start()])
        if language in {"text", "txt"} and not filename:
            # A text fence is often used to visually set off wording that EVE is
            # meant to read.  Treat it as prose unless the user asked for a file.
            spoken_parts.append(content.rstrip())
            cursor = match.end()
            continue
        if not filename:
            ext = EXTENSIONS.get(language, ".txt")
            filename = f"eve-script{'' if number == 1 else f'-{number}'}{ext}"
        mime = mimetypes.guess_type(filename)[0] or "text/plain"
        artifacts.append({
            "filename": filename,
            "mime": mime,
            "base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        })
        cursor = match.end()
    spoken_parts.append(answer[cursor:])
    spoken = "".join(spoken_parts).strip()
    spoken = re.sub(r"\n{3,}", "\n\n", spoken)
    if not spoken:
        names = ", ".join(item["filename"] for item in artifacts)
        spoken = f"Ich habe {names} erstellt und als Download bereitgestellt."
    return spoken, artifacts


def _filename(info: str) -> str | None:
    match = re.search(r"(?:filename|file)\s*=\s*[\"']?([^\s\"']+)", info, re.I)
    if not match:
        match = re.search(r"(?:^|\s)([\w.-]+\.[A-Za-z0-9]{1,8})(?:\s|$)", info)
    return _safe_name(match.group(1)) if match else None


def _requested_filename(request: str) -> str | None:
    match = re.search(r"\b([\w.-]+\.(?:py|js|ts|sh|ps1|html|css|json|ya?ml|sql|md|txt))\b", request, re.I)
    return _safe_name(match.group(1)) if match else None


def _safe_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]", "-", Path(name).name).strip(".-")
    return clean or "eve-script.txt"
