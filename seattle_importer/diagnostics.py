from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SECRET_PATTERNS = (
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)*"), "[JWT]"),
    (re.compile(r"sb_(?:secret|publishable)_[A-Za-z0-9_-]+"), "[KEY]"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(apikey[=:]\s*)\S+"), r"\1[REDACTED]"),
)
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")
_HOST_PATTERN = re.compile(r"host='([^']+)'")


def sanitize_text(value: str) -> str:
    text = value
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)

    def strip_query(match: re.Match[str]) -> str:
        parts = urlsplit(match.group(0).rstrip(").,;"))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    return _URL_PATTERN.sub(strip_query, text)


def _request_of(exc: BaseException):
    response = getattr(exc, "response", None)
    request = getattr(response, "request", None) if response is not None else None
    if request is None:
        request = getattr(exc, "request", None)
    return response, request


def failure_details(exc: BaseException) -> dict[str, Any]:
    response, request = _request_of(exc)
    host = None
    path = None
    method = None
    if request is not None:
        method = getattr(request, "method", None)
        parts = urlsplit(getattr(request, "url", "") or "")
        host = parts.hostname
        path = parts.path or None
    if not host:
        match = _HOST_PATTERN.search(str(exc))
        if match:
            host = match.group(1)

    status = getattr(response, "status_code", None) if response is not None else None
    error_code = None
    error_message = None
    if response is not None:
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            raw_code = body.get("code") or body.get("error_code")
            raw_message = body.get("message") or body.get("error") or body.get("msg")
            if raw_code:
                error_code = sanitize_text(str(raw_code))[:80]
            if raw_message:
                error_message = sanitize_text(str(raw_message))[:300]

    summary = error_message or sanitize_text(f"{type(exc).__name__}: {exc}")
    return {
        "method": method,
        "host": host,
        "path": path,
        "status": status,
        "error_code": error_code,
        "summary": summary[:300],
    }


def layer_for(exc: BaseException) -> str:
    host = failure_details(exc).get("host") or ""
    if host.endswith(".supabase.co"):
        return "importer-database"
    if host:
        return "published-feed"
    return "importer"


def format_failure(exc: BaseException, layer: str, source: str | None = None) -> str:
    details = failure_details(exc)
    parts = [f"layer={layer}"]
    if source:
        parts.append(f"source={source}")
    if details.get("method"):
        parts.append(f"method={details['method']}")
    if details.get("host"):
        parts.append(f"host={details['host']}")
    if details.get("path"):
        parts.append(f"path={details['path']}")
    status = details.get("status")
    parts.append(f"status={status if status else 'none'}")
    if details.get("error_code"):
        parts.append(f"error_code={details['error_code']}")
    parts.append(f"error={details['summary']}")
    return " ".join(parts)


def format_producer_failure(source: str, status: dict[str, Any]) -> str:
    code = sanitize_text(str(status.get("code") or "producer_error"))
    message = sanitize_text(str(status.get("message") or "producer failed"))
    return f"layer=producer source={source} code={code} status=none error={message}"
