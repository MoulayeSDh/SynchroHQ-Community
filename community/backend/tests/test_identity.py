import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.identity.security import decode_access_token


def test_access_token_subject_is_verified() -> None:
    settings = get_settings()
    user_id = uuid.uuid4()
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    assert decode_access_token(token) == user_id
    with pytest.raises(HTTPException):
        decode_access_token(token + "invalid")
