"""
Security utilities: JWT creation/validation and OAuth token encryption.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Password hashing (not used for OAuth but available for future admin users)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.APP_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.
    Raises TokenExpiredError or InvalidTokenError on failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.APP_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise TokenExpiredError() from exc
        logger.warning("invalid_jwt", error=str(exc))
        raise InvalidTokenError() from exc


def get_user_id_from_token(token: str) -> str:
    """Extract user_id from a validated JWT."""
    payload = decode_access_token(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise InvalidTokenError()
    return user_id


# ── OAuth Token Encryption ────────────────────────────────────────────────────


def _get_fernet() -> Fernet:
    """Get Fernet encryption instance. Generates a key if not configured (dev only)."""
    key = settings.ENCRYPTION_KEY
    if not key:
        if settings.is_production:
            raise RuntimeError("ENCRYPTION_KEY must be set in production!")
        # Dev fallback — generate and warn
        key = Fernet.generate_key().decode()
        logger.warning(
            "encryption_key_missing",
            message="Using auto-generated encryption key. Set ENCRYPTION_KEY in .env!",
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        raise ValueError("ENCRYPTION_KEY is invalid. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")


def encrypt_token(plain_token: str) -> str:
    """Encrypt an OAuth token for safe storage in MongoDB."""
    fernet = _get_fernet()
    return fernet.encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a stored OAuth token."""
    fernet = _get_fernet()
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except InvalidToken as exc:
        logger.error("token_decryption_failed")
        raise InvalidTokenError() from exc


# ── Password Helpers (Admin Use) ──────────────────────────────────────────────


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
