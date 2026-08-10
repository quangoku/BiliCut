"""HTTP transport selection and error normalization for CapCut TTS."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional

import requests as pyrequests

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import exceptions as curl_exceptions
except (ImportError, OSError):
    curl_requests = None
    curl_exceptions = None


@dataclass
class CapCutTransportError(RuntimeError):
    kind: str
    message: str
    status_code: int = 0
    retry_after: Optional[float] = None
    original: Optional[BaseException] = None

    def __str__(self) -> str:
        return self.message

    @property
    def retryable_create(self) -> bool:
        return self.kind in {"dns", "connect", "connect_timeout"} or self.status_code == 429

    @property
    def retryable_poll(self) -> bool:
        return self.kind in {"dns", "connect", "connect_timeout", "read_timeout"} or self.status_code == 429


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (target - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _normalize_requests_error(exc: BaseException) -> CapCutTransportError:
    if isinstance(exc, pyrequests.exceptions.ConnectTimeout):
        kind = "connect_timeout"
    elif isinstance(exc, pyrequests.exceptions.ReadTimeout):
        kind = "read_timeout"
    elif isinstance(exc, pyrequests.exceptions.SSLError):
        kind = "tls"
    elif isinstance(exc, pyrequests.exceptions.ConnectionError):
        detail = str(exc).lower()
        kind = "dns" if "name resolution" in detail or "getaddrinfo" in detail else "connect"
    else:
        kind = "unknown"
    return CapCutTransportError(kind, _safe_error_message(kind), original=exc)


def _normalize_curl_error(exc: BaseException) -> CapCutTransportError:
    if curl_exceptions is not None and isinstance(exc, curl_exceptions.DNSError):
        kind = "dns"
    elif curl_exceptions is not None and isinstance(exc, curl_exceptions.SSLError):
        kind = "tls"
    elif curl_exceptions is not None and isinstance(exc, curl_exceptions.Timeout):
        detail = str(exc).lower()
        kind = "connect_timeout" if "connect" in detail else "read_timeout"
    elif curl_exceptions is not None and isinstance(exc, curl_exceptions.ConnectionError):
        kind = "connect"
    else:
        kind = "unknown"
    return CapCutTransportError(kind, _safe_error_message(kind), original=exc)


def _safe_error_message(kind: str) -> str:
    return {
        "dns": "Không phân giải được máy chủ CapCut TTS.",
        "connect": "Không thể kết nối tới máy chủ CapCut TTS.",
        "connect_timeout": "Kết nối CapCut TTS quá thời gian.",
        "read_timeout": "CapCut TTS phản hồi quá thời gian.",
        "tls": "Không thể thiết lập kết nối TLS an toàn tới CapCut TTS.",
    }.get(kind, "Lỗi kết nối không xác định tới CapCut TTS.")


class CapCutTTSSession:
    """Small requests-compatible wrapper used only by the TTS client."""

    def __init__(self, session: Any, name: str):
        self._session = session
        self.transport_name = name

    def _request(self, method: Callable, *args, **kwargs):
        try:
            response = method(*args, **kwargs)
        except pyrequests.exceptions.RequestException as exc:
            raise _normalize_requests_error(exc) from exc
        except Exception as exc:
            if curl_exceptions is not None and isinstance(exc, curl_exceptions.RequestException):
                raise _normalize_curl_error(exc) from exc
            raise

        if getattr(response, "status_code", 0) == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            raise CapCutTransportError(
                kind="http",
                message="CapCut TTS HTTP 429: quá nhiều yêu cầu.",
                status_code=429,
                retry_after=retry_after,
            )
        return response

    def get(self, *args, **kwargs):
        return self._request(self._session.get, *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._request(self._session.post, *args, **kwargs)

    def close(self) -> None:
        close = getattr(self._session, "close", None)
        if close:
            close()


def create_tts_session() -> CapCutTTSSession:
    """Prefer curl_cffi and fall back before the first request if unavailable."""
    if curl_requests is not None:
        try:
            session = curl_requests.Session(verify=True, trust_env=True)
            return CapCutTTSSession(session, "curl_cffi")
        except (OSError, RuntimeError, TypeError):
            pass

    session = pyrequests.Session()
    session.verify = True
    session.trust_env = True
    return CapCutTTSSession(session, "requests fallback")


__all__ = ["CapCutTransportError", "CapCutTTSSession", "create_tts_session"]
