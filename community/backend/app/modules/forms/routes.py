import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.authorization.service import is_allowed
from app.modules.forms.models import Form, FormAuditEvent, FormVersion
from app.modules.forms.schemas import (
    Answers,
    Envelope,
    FormCreate,
    FormRead,
    ValidationResult,
    VersionRead,
)
from app.modules.forms.validation import validate_answers, validate_envelope
from app.modules.identity.security import get_current_user_id
from app.modules.users.models import User

router = APIRouter(prefix="/api/forms", tags=["forms"])


def current_user(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Inactive or unknown user")
    return user


def allowed(session: Session, user: User, form: Form, action: str) -> bool:
    return form.tenant_id == user.tenant_id and is_allowed(
        session,
        user_id=user.id,
        action=action,
        territory_id=form.territory_id,
        required_clearance=form.required_clearance,
    )


def get_form(
    session: Session, user: User, form_id: uuid.UUID, action: str, lock: bool = False
) -> Form:
    query = select(Form).where(Form.id == form_id, Form.tenant_id == user.tenant_id)
    if lock:
        query = query.with_for_update()
    form = session.scalar(query)
    if form is None:
        raise HTTPException(404, "Form not found")
    if not allowed(session, user, form, action):
        raise HTTPException(403, "Permission denied")
    if action != "forms:read" and (not form.active or form.archived):
        raise HTTPException(409, "Form is inactive or archived")
    return form


def get_version(session: Session, form_id: uuid.UUID, version: int) -> FormVersion:
    item = session.scalar(
        select(FormVersion).where(
            FormVersion.form_id == form_id,
            FormVersion.version == version,
        )
    )
    if item is None:
        raise HTTPException(404, "Version not found")
    return item


def commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Form code or version already exists") from exc


def form_read(session: Session, user: User, form: Form) -> FormRead:
    return FormRead.model_validate(form).model_copy(
        update={
            "actions": {
                "collect": form.active
                and not form.archived
                and allowed(session, user, form, "drafts:sync"),
                "manage": form.active
                and not form.archived
                and allowed(session, user, form, "forms:manage"),
                "publish": form.active
                and not form.archived
                and allowed(session, user, form, "forms:publish"),
            }
        }
    )


@router.get("", response_model=list[FormRead])
def list_forms(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[FormRead]:
    # Filter before pagination so inaccessible rows do not leak through counts or page gaps.
    forms = session.scalars(
        select(Form).where(Form.tenant_id == user.tenant_id).order_by(Form.code)
    )
    visible = [form for form in forms if allowed(session, user, form, "forms:read")]
    return [form_read(session, user, form) for form in visible[offset : offset + limit]]


@router.post("", response_model=FormRead, status_code=201)
def create_form(
    body: FormCreate, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> FormRead:
    form = Form(tenant_id=user.tenant_id, **body.model_dump())
    if not allowed(session, user, form, "forms:manage"):
        raise HTTPException(403, "Permission denied")
    session.add(form)
    commit(session)
    return form_read(session, user, form)


@router.get("/{form_id}", response_model=FormRead)
def read_form(
    form_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> FormRead:
    return form_read(session, user, get_form(session, user, form_id, "forms:read"))


@router.get("/{form_id}/versions", response_model=list[VersionRead])
def list_versions(
    form_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[FormVersion]:
    get_form(session, user, form_id, "forms:read")
    return list(
        session.scalars(
            select(FormVersion).where(FormVersion.form_id == form_id).order_by(FormVersion.version)
        )
    )


@router.post("/{form_id}/versions", response_model=VersionRead, status_code=201)
def create_version(
    form_id: uuid.UUID,
    body: Envelope,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> FormVersion:
    get_form(session, user, form_id, "forms:manage", lock=True)
    validate_envelope(body)
    latest = (
        session.scalar(select(func.max(FormVersion.version)).where(FormVersion.form_id == form_id))
        or 0
    )
    item = FormVersion(form_id=form_id, version=latest + 1, **body.model_dump())
    session.add(item)
    commit(session)
    return item


@router.get("/{form_id}/versions/{version}", response_model=VersionRead)
def read_version(
    form_id: uuid.UUID,
    version: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> FormVersion:
    get_form(session, user, form_id, "forms:read")
    return get_version(session, form_id, version)


@router.patch("/{form_id}/versions/{version}", response_model=VersionRead)
def edit_version(
    form_id: uuid.UUID,
    version: int,
    body: Envelope,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> FormVersion:
    get_form(session, user, form_id, "forms:manage", lock=True)
    item = get_version(session, form_id, version)
    if item.status != "DRAFT":
        raise HTTPException(409, "Published and retired content is immutable")
    validate_envelope(body)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    commit(session)
    return item


def transition(
    session: Session, user: User, form_id: uuid.UUID, version: int, target: str
) -> FormVersion:
    form = get_form(session, user, form_id, "forms:publish", lock=True)
    item = get_version(session, form_id, version)
    expected = "DRAFT" if target == "PUBLISHED" else "PUBLISHED"
    if item.status != expected:
        raise HTTPException(409, f"Expected {expected} version")
    now = datetime.now(UTC)
    if target == "PUBLISHED":
        validate_envelope(Envelope.model_validate(item, from_attributes=True))
        item.published_at, item.published_by = now, user.id
    else:
        item.retired_at = now
    item.status = target
    session.add(
        FormAuditEvent(
            tenant_id=form.tenant_id,
            actor_id=user.id,
            actor_name=user.display_name,
            form_id=form.id,
            version=version,
            action=f"FORM_VERSION_{target}",
            occurred_at=now,
        )
    )
    commit(session)
    return item


@router.post("/{form_id}/versions/{version}/publish", response_model=VersionRead)
def publish(
    form_id: uuid.UUID,
    version: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> FormVersion:
    return transition(session, user, form_id, version, "PUBLISHED")


@router.post("/{form_id}/versions/{version}/retire", response_model=VersionRead)
def retire(
    form_id: uuid.UUID,
    version: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> FormVersion:
    return transition(session, user, form_id, version, "RETIRED")


@router.post("/{form_id}/versions/{version}/validate", response_model=ValidationResult)
def validate(
    form_id: uuid.UUID,
    version: int,
    body: Answers,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ValidationResult:
    get_form(session, user, form_id, "forms:read")
    item = get_version(session, form_id, version)
    return validate_answers(item.data_schema, body.answers)
