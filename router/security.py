import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(result).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        result = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(result, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class WindowLimiter:
    """Single-worker, monotonic rolling window; stale keys are evicted."""

    def __init__(self):
        self.entries = defaultdict(deque)
        self.last_cleanup = 0

    def check(self, key: str, limit: int, window: float = 60):
        now = time.monotonic()
        if now - self.last_cleanup > 60:
            self.entries = defaultdict(
                deque, {k: v for k, v in self.entries.items() if v and v[-1] > now - 600}
            )
            self.last_cleanup = now
        entries = self.entries[key]
        while entries and entries[0] <= now - window:
            entries.popleft()
        if len(entries) >= limit:
            raise HTTPException(
                429,
                "rate_limited",
                headers={"Retry-After": str(max(1, int(entries[0] + window - now) + 1))},
            )
        entries.append(now)
