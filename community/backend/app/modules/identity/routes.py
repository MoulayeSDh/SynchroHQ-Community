import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.identity.security import get_current_user_id
from app.modules.users.models import User

router = APIRouter(prefix="/api", tags=["identity"])


class CurrentUser(BaseModel):
    id: uuid.UUID
    display_name: str
    tenant_id: uuid.UUID
    offline_edit_seconds: int


@router.get("/me", response_model=CurrentUser)
def me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> CurrentUser:
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return CurrentUser(
        id=user.id,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        offline_edit_seconds=get_settings().offline_edit_seconds,
    )
