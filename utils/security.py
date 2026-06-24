"""Security helpers: salted hashing for IP/UA, HMAC verification, base62 encoding.

We NEVER store raw IP addresses or user agents — only salted SHA-256 hashes.
The salt comes from Settings (WEBHOOK_SECRET or a static fallback for dev).
"""
from __future__ import annotations

import hashlib
import hmac
import os

BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def salted_hash(value: str, salt: str) -> str:
    """Return a hex SHA-256 hash of salt+value. Never store raw value."""
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def hash_ip(ip: str, salt: str) -> str:
    """Hash an IP address with salt."""
    return salted_hash(ip, salt)


def hash_ua(user_agent: str, salt: str) -> str:
    """Hash a user-agent string with salt."""
    return salted_hash(user_agent, salt)


def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 signature (constant-time)."""
    expected = hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def compute_dedupe_hash(provider: str, body: bytes) -> str:
    """Compute a stable dedupe hash from provider + raw body."""
    return hashlib.sha256(f"{provider}:{body.decode(errors='replace')}".encode()).hexdigest()


def encode_base62(num: int) -> str:
    """Encode a non-negative integer as a base62 string."""
    if num == 0:
        return BASE62_ALPHABET[0]
    chars: list[str] = []
    while num > 0:
        chars.append(BASE62_ALPHABET[num % 62])
        num //= 62
    return "".join(reversed(chars))


def generate_referral_code(user_id: int) -> str:
    """Generate a short stable referral code: base62(user_id) + 1 checksum char.

    Deterministic: same user_id always yields the same code (idempotent get_or_create).
    """
    base = encode_base62(user_id)
    checksum = sum(BASE62_ALPHABET.index(c) for c in base) % 62
    return f"{base}{BASE62_ALPHABET[checksum]}"


def generate_idempotency_key(prefix: str, user_id: int, offer_id: int) -> str:
    """Generate a unique idempotency key for payments."""
    rand = os.urandom(8).hex()
    return f"{prefix}:{user_id}:{offer_id}:{rand}"
