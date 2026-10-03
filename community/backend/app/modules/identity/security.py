import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.identity.models import AuthSession, Tenant
from app.modules.users.models import User

bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHasher(type=Type.ID)
_dummy_hash = password_hasher.hash("unavailable-account")


def hash_password(password: str) -> str:
    if len(password) < 14 or len(password.encode("utf-8")) > 1024:
        raise ValueError("Password must be 14-1024 UTF-8 bytes")
    return password_hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        valid = password_hasher.verify(stored_hash or _dummy_hash, password)
        return bool(stored_hash) and valid
    except (VerificationError, VerifyMismatchError):
        return False


def access_claims(token: str) -> tuple[uuid.UUID, uuid.UUID | None]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={
                "require": [
                    "sub", "iss", "aud", "exp",
                    *(["iat"] if settings.app_env == "production" else []),
                ]
            },
        )
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["jti"]) if "jti" in payload else None
        if settings.app_env == "production" and (
            payload.get("typ") != "access" or session_id is None
        ):
            raise ValueError("Unmanaged production token")
        return user_id, session_id
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc


def decode_access_token(token: str) -> uuid.UUID:
    return access_claims(token)[0]


def issue_access_token(session: Session, user: User) -> str:
    now = datetime.now(UTC)
    record = AuthSession(user_id=user.id, issued_at=now, expires_at=now + timedelta(hours=1))
    session.add(record)
    session.flush()
    settings = get_settings()
    return jwt.encode(
        {
            "sub": str(user.id), "jti": str(record.id), "typ": "access",
            "iss": settings.auth_issuer, "aud": settings.auth_audience,
            "iat": now, "exp": record.expires_at,
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> uuid.UUID:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    user_id, session_id = access_claims(credentials.credentials)
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Session unavailable")
    if get_settings().app_env == "production":
        tenant = session.get(Tenant, user.tenant_id)
        if tenant is None or not tenant.active:
            raise HTTPException(status_code=401, detail="Session unavailable")
    if session_id is not None:
        record = session.get(AuthSession, session_id)
        if (
            record is None or record.user_id != user_id or record.revoked_at is not None
            or _aware(record.expires_at) <= datetime.now(UTC)
        ):
            raise HTTPException(status_code=401, detail="Session unavailable")
    return user_id
