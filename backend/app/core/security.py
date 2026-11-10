"""Password hashing (PBKDF2-SHA256, standard library) and JWT tokens."""
import base64
import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iterations)
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def temporary_password(length: int = 10) -> str:
    """Readable temporary password, e.g. 'Kx7m-Qp2a'."""
    alphabet = string.ascii_letters + string.digits
    alphabet = alphabet.translate({ord(c): None for c in "0OIl1"})
    raw = "".join(secrets.choice(alphabet) for _ in range(length - 1))
    return raw[:4] + "-" + raw[4:]


def create_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
