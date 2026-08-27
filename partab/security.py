from dataclasses import dataclass
from datetime import datetime
import hashlib
import secrets
import threading
import time


@dataclass
class AccessRequest:
    request_id: str
    fingerprint: str
    ip: str
    user_agent: str
    device: str
    created_at: float
    status: str = "pending"
    token: str | None = None

    def as_public_dict(self):
        return {
            "id": self.request_id,
            "ip": self.ip,
            "device": self.device,
            "created_at": datetime.fromtimestamp(self.created_at).strftime("%H:%M:%S"),
            "status": self.status,
        }


def describe_user_agent(user_agent: str) -> str:
    ua = user_agent or ""
    lower = ua.lower()

    if "iphone" in lower:
        device = "iPhone"
    elif "ipad" in lower:
        device = "iPad"
    elif "android" in lower:
        device = "Android device"
    elif "windows" in lower:
        device = "Windows PC"
    elif "macintosh" in lower or "mac os" in lower:
        device = "Mac"
    elif "linux" in lower:
        device = "Linux device"
    else:
        device = "Unknown device"

    if "edg/" in lower:
        browser = "Edge"
    elif "chrome/" in lower and "chromium" not in lower:
        browser = "Chrome"
    elif "firefox/" in lower:
        browser = "Firefox"
    elif "safari/" in lower and "chrome/" not in lower:
        browser = "Safari"
    else:
        browser = "Browser"

    return f"{device} · {browser}"


class AccessManager:
    REQUEST_TTL = 60 * 60

    def __init__(self):
        self._lock = threading.RLock()
        self._secure = False
        self._requests: dict[str, AccessRequest] = {}
        self._request_by_fingerprint: dict[str, str] = {}
        self._approved_tokens: dict[str, str] = {}

    @property
    def secure(self) -> bool:
        with self._lock:
            return self._secure

    def set_secure(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        with self._lock:
            if self._secure != enabled:
                self._secure = enabled
                self._requests.clear()
                self._request_by_fingerprint.clear()
                self._approved_tokens.clear()
            return self._secure

    @staticmethod
    def _fingerprint(ip: str, user_agent: str) -> str:
        raw = f"{ip}\0{user_agent or ''}".encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()

    def is_approved(self, token: str | None, ip: str, user_agent: str) -> bool:
        if not token:
            return False
        fingerprint = self._fingerprint(ip, user_agent)
        with self._lock:
            return self._approved_tokens.get(token) == fingerprint

    def request_access(self, ip: str, user_agent: str) -> tuple[AccessRequest, bool]:
        fingerprint = self._fingerprint(ip, user_agent)
        now = time.time()

        with self._lock:
            self._cleanup_locked(now)

            existing_id = self._request_by_fingerprint.get(fingerprint)
            if existing_id:
                existing = self._requests.get(existing_id)
                if existing:
                    return existing, False

            request = AccessRequest(
                request_id=secrets.token_urlsafe(24),
                fingerprint=fingerprint,
                ip=ip,
                user_agent=user_agent or "",
                device=describe_user_agent(user_agent),
                created_at=now,
            )
            self._requests[request.request_id] = request
            self._request_by_fingerprint[fingerprint] = request.request_id
            return request, True

    def pending_requests(self) -> list[dict]:
        with self._lock:
            self._cleanup_locked(time.time())
            pending = [
                request for request in self._requests.values()
                if request.status == "pending"
            ]
            pending.sort(key=lambda item: item.created_at)
            return [request.as_public_dict() for request in pending]

    def decide(self, request_id: str, approve: bool) -> bool:
        with self._lock:
            request = self._requests.get(request_id)
            if not request or request.status != "pending":
                return False

            if approve:
                token = secrets.token_urlsafe(32)
                request.status = "approved"
                request.token = token
                self._approved_tokens[token] = request.fingerprint
            else:
                request.status = "denied"
                request.token = None
            return True

    def access_status(self, request_id: str, ip: str, user_agent: str):
        with self._lock:
            if not self._secure:
                return "open", None

            request = self._requests.get(request_id)
            if not request:
                return "expired", None

            fingerprint = self._fingerprint(ip, user_agent)
            if request.fingerprint != fingerprint:
                return "invalid", None

            return request.status, request.token

    def _cleanup_locked(self, now: float):
        expired = [
            request_id
            for request_id, request in self._requests.items()
            if now - request.created_at > self.REQUEST_TTL
        ]
        for request_id in expired:
            request = self._requests.pop(request_id)
            if self._request_by_fingerprint.get(request.fingerprint) == request_id:
                self._request_by_fingerprint.pop(request.fingerprint, None)
            if request.token:
                self._approved_tokens.pop(request.token, None)


access_manager = AccessManager()
