"""NPOPS security — password hashing (PBKDF2-HMAC-SHA256, 200k iters),
signed session tokens, CSRF tokens, constant-time comparisons.

Rolling our own instead of pulling passlib: the primitives are stdlib
and the constructions are the standard ones (NIST SP 800-132 PBKDF,
random 256-bit tokens, HMAC-signed stateless sessions).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

PBKDF_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt,
                             PBKDF_ITERATIONS)
    return f"pbkdf2${PBKDF_ITERATIONS}${base64.b64encode(salt).decode()}$" \
           f"{base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_session_id() -> str:
    return secrets.token_hex(32)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class TokenSigner:
    """HMAC-SHA256 signed payloads: base64(payload).base64(hmac)."""

    def __init__(self, secret: bytes):
        self.secret = secret

    def sign(self, payload: dict, ttl: int | None = None) -> str:
        body = dict(payload)
        if ttl:
            body["exp"] = int(time.time()) + ttl
        raw = json.dumps(body, separators=(",", ":")).encode()
        sig = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + \
            base64.urlsafe_b64encode(sig).decode().rstrip("=")

    def verify(self, token: str) -> dict | None:
        try:
            raw_b64, sig_b64 = token.split(".")
            raw = base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4))
            sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
            expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(sig, expected):
                return None
            body = json.loads(raw)
            if "exp" in body and body["exp"] < time.time():
                return None
            return body
        except (ValueError, TypeError, json.JSONDecodeError):
            return None


def generate_secret() -> bytes:
    return secrets.token_bytes(32)


def load_or_create_secret(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) >= 32:
            return data
    except FileNotFoundError:
        pass
    data = generate_secret()
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)
    return data
