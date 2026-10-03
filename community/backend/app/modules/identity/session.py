"""Presentation metadata and explicitly opt-in synthetic local pilot accounts."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.authorization.models import AssignmentScope, Permission, Role
from app.modules.authorization.service import matching_assignments
from app.modules.identity.models import AuthSession, Tenant, UserCredential
from app.modules.identity.security import (
    access_claims,
    bearer,
    get_current_user_id,
    hash_password,
    issue_access_token,
    verify_password,
)
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User

router = APIRouter(prefix="/api/session", tags=["session"])
DEMO_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "synchrohq:phase6b-demo")
ACCOUNTS = ("author_1", "reviewer", "regional", "central", "other_wilaya", "admin")


def active_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(401, "SESSION_UNAVAILABLE")
    return user


def presentation(session: Session, user: User) -> dict[str, Any]:
    permissions = list(session.scalars(select(Permission).order_by(Permission.code)))
    territories = session.scalars(
        select(Territory).where(Territory.tenant_id == user.tenant_id, Territory.active.is_(True))
    )
    visible: list[dict[str, Any]] = []
    effective: set[str] = set()
    assignments: dict[str, dict[str, Any]] = {}
    for territory in territories:
        actions = []
        for permission in permissions:
            matches = matching_assignments(
                session,
                user_id=user.id,
                action=permission.code,
                territory_id=territory.id,
                required_clearance=0,
            )
            if matches:
                actions.append(permission.code)
            for assignment in matches:
                org = session.get(Organization, assignment.organization_id)
                role = session.get(Role, assignment.role_id)
                assert org is not None and role is not None
                scopes = session.scalars(
                    select(AssignmentScope).where(AssignmentScope.assignment_id == assignment.id)
                )
                previous_territories = assignments.get(str(assignment.id), {}).get(
                    "territory_ids", []
                )
                assignments[str(assignment.id)] = {
                    "territory_ids": list(set([*previous_territories, str(territory.id)])),
                    "id": str(assignment.id),
                    "organization": org.name,
                    "organization_id": str(org.id),
                    "role": role.code,
                    "clearance": assignment.clearance_level,
                    "scopes": [
                        {"territory_id": str(s.territory_id), "coverage": s.coverage}
                        for s in scopes
                    ],
                }
        if actions:
            visible.append(
                {
                    "id": str(territory.id),
                    "name": territory.name,
                    "type": territory.type_code,
                    "actions": actions,
                }
            )
            effective.update(actions)
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "display_name": user.display_name,
        "offline_edit_seconds": get_settings().offline_edit_seconds,
        "permissions": sorted(effective),
        "territories": visible,
        "assignments": list(assignments.values()),
    }


@router.get("")
def current_session(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return presentation(session, active_user(session, user_id))


def require_demo() -> None:
    settings = get_settings()
    if settings.app_env != "development" or not settings.demo_login_enabled:
        raise HTTPException(404, "Not found")


@router.get("/demo")
def demo_accounts(session: Session = Depends(get_session)) -> list[str]:
    require_demo()
    return [
        code
        for code in ACCOUNTS
        if session.scalar(
            select(User.id).where(
                User.id == uuid.uuid5(DEMO_NAMESPACE, "user:" + code),
                User.tenant_id == DEMO_NAMESPACE,
                User.subject == "phase6b:" + code,
                User.active.is_(True),
            )
        )
        is not None
    ]


class DemoLogin(BaseModel):
    account: Literal["author_1", "reviewer", "regional", "central", "other_wilaya", "admin"]


@router.post("/demo")
def demo_login(body: DemoLogin, session: Session = Depends(get_session)) -> dict[str, str]:
    require_demo()
    user = active_user(session, uuid.uuid5(DEMO_NAMESPACE, "user:" + body.account))
    if user.tenant_id != DEMO_NAMESPACE or user.subject != "phase6b:" + body.account:
        raise HTTPException(404, "Not found")
    if not presentation(session, user)["permissions"]:
        raise HTTPException(403, "SESSION_UNAVAILABLE")
    token = issue_access_token(session, user)
    session.commit()
    return {"token": token}


class PasswordLogin(BaseModel):
    identifier: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
def password_login(body: PasswordLogin, session: Session = Depends(get_session)) -> dict[str, str]:
    identifier = body.identifier.strip().casefold()
    if not 3 <= len(identifier) <= 255 or len(body.password) > 1024:
        raise HTTPException(401, "INVALID_CREDENTIALS")
    user = session.scalar(select(User).where(User.subject == identifier))
    credential = session.scalar(
        select(UserCredential).where(UserCredential.user_id == user.id).with_for_update()
    ) if user else None
    if not verify_password(credential.password_hash if credential else None, body.password):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    tenant = session.get(Tenant, user.tenant_id) if user else None
    if user is None or not user.active or tenant is None or not tenant.active:
        raise HTTPException(401, "INVALID_CREDENTIALS")
    token = issue_access_token(session, user)
    session.commit()
    return {"token": token}


@router.post("/change-password")
def change_password(
    body: PasswordChange,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if len(body.current_password.encode("utf-8")) > 1024:
        raise HTTPException(401, "INVALID_CREDENTIALS")
    if len(body.new_password.encode("utf-8")) > 1024:
        raise HTTPException(400, "PASSWORD_POLICY")
    credential = session.scalar(
        select(UserCredential).where(UserCredential.user_id == user_id).with_for_update()
    )
    if not verify_password(credential.password_hash if credential else None, body.current_password):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    if body.new_password == body.current_password:
        raise HTTPException(400, "PASSWORD_UNCHANGED")
    try:
        new_hash = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, "PASSWORD_POLICY") from exc
    assert credential is not None
    now = datetime.now(UTC)
    credential.password_hash = new_hash
    credential.password_changed_at = now
    for record in session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    ):
        record.revoked_at = now
    token = issue_access_token(session, active_user(session, user_id))
    session.commit()
    return {"token": token}


@router.post("/logout", status_code=204)
def password_logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> None:
    assert credentials is not None
    _, session_id = access_claims(credentials.credentials)
    if session_id is not None:
        record = session.get(AuthSession, session_id)
        if record is not None and record.user_id == user_id:
            record.revoked_at = datetime.now(UTC)
            session.commit()


@router.get("/administration")
def administration(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user = active_user(session, user_id)
    info = presentation(session, user)
    territories = [t for t in info["territories"] if "administration:read" in t["actions"]]
    if not territories:
        raise HTTPException(403, "Permission denied")
    # Directory permission is explicit and separate from form management.
    visible_users = []
    organizations: dict[str, dict[str, str]] = {}
    for candidate in session.scalars(select(User).where(User.tenant_id == user.tenant_id)):
        metadata = presentation(session, candidate) if candidate.active else None
        if not metadata or not any(
            t["id"] in {v["id"] for v in territories} for t in metadata["territories"]
        ):
            continue
        visible_users.append({"id": str(candidate.id), "name": candidate.display_name})
        for assignment in metadata["assignments"]:
            if not set(assignment["territory_ids"]).intersection({t["id"] for t in territories}):
                continue
            for org in session.scalars(
                select(Organization).where(
                    Organization.tenant_id == user.tenant_id,
                    Organization.id == uuid.UUID(assignment["organization_id"]),
                )
            ):
                organizations[str(org.id)] = {"id": str(org.id), "name": org.name, "code": org.code}
    return {
        "users": visible_users,
        "organizations": list(organizations.values()),
        "territories": territories,
    }
