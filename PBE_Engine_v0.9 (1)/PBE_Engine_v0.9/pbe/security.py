import base64, hashlib, hmac, os
from datetime import datetime, timedelta, timezone
import jwt
from pbe.settings import settings


def validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if len(password) > 1024:
        raise ValueError("Password is too long")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("Password must include at least one letter and one number")


def validate_runtime_config() -> None:
    if settings.APP_ENV == "production":
        if len(settings.JWT_SECRET) < 32 or settings.JWT_SECRET == "dev-only-change-me":
            raise RuntimeError("Production requires JWT_SECRET with at least 32 characters; do not use the development default")
        if settings.JWT_EXPIRES_MINUTES < 5 or settings.JWT_EXPIRES_MINUTES > 1440:
            raise RuntimeError("JWT_EXPIRES_MINUTES must be between 5 and 1440 in production")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(dk).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(hash_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def issue_token(user_id: str, workspace_id: str, tenant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": user_id, "workspace_id": workspace_id, "tenant_id": tenant_id,
        "role": role, "iat": now, "nbf": now, "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE, "exp": now + timedelta(minutes=settings.JWT_EXPIRES_MINUTES)}
    return jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str):
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"], issuer=settings.JWT_ISSUER, audience=settings.JWT_AUDIENCE)


def require_role(claims: dict, *roles: str) -> dict:
    if claims.get("role") not in roles:
        from fastapi import HTTPException
        raise HTTPException(403, "Insufficient workspace role")
    return claims
