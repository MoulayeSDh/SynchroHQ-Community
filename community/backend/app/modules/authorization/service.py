import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


def _is_descendant(session: Session, territory_id: uuid.UUID, ancestor_id: uuid.UUID) -> bool:
    current_id: uuid.UUID | None = territory_id
    visited: set[uuid.UUID] = set()
    while current_id is not None and current_id not in visited:
        if current_id == ancestor_id:
            return True
        visited.add(current_id)
        current_id = session.scalar(select(Territory.parent_id).where(Territory.id == current_id))
    return False


def matching_assignments(
    session: Session,
    *,
    user_id: uuid.UUID,
    action: str,
    territory_id: uuid.UUID,
    required_clearance: int,
    at: datetime | None = None,
) -> list[UserAssignment]:
    """Evaluate permission, clearance and territorial scope; deny by default."""
    now = at or datetime.now(UTC)
    user = session.get(User, user_id)
    if user is None or not user.active:
        return []
    territory = session.get(Territory, territory_id)
    if territory is None or not territory.active or territory.tenant_id != user.tenant_id:
        return []

    assignments = session.scalars(
        select(UserAssignment)
        .join(Organization, Organization.id == UserAssignment.organization_id)
        .join(Role, Role.id == UserAssignment.role_id)
        .where(
            UserAssignment.user_id == user_id,
            Organization.tenant_id == user.tenant_id,
            Organization.active.is_(True),
            Role.tenant_id == user.tenant_id,
            UserAssignment.active.is_(True),
            UserAssignment.valid_from <= now,
            (UserAssignment.valid_to.is_(None) | (UserAssignment.valid_to > now)),
            UserAssignment.clearance_level >= required_clearance,
        )
    )
    permission_id = session.scalar(select(Permission.id).where(Permission.code == action))
    if permission_id is None:
        return []

    result: list[UserAssignment] = []
    for assignment in assignments:
        has_permission = session.scalar(
            select(RolePermission.role_id).where(
                RolePermission.role_id == assignment.role_id,
                RolePermission.permission_id == permission_id,
            )
        )
        if has_permission is None:
            continue
        scopes = session.scalars(
            select(AssignmentScope).where(AssignmentScope.assignment_id == assignment.id)
        )
        for scope in scopes:
            if scope.coverage == "SELF" and scope.territory_id == territory_id:
                result.append(assignment)
                break
            if scope.coverage == "DESCENDANTS" and _is_descendant(
                session, territory_id, scope.territory_id
            ):
                result.append(assignment)
                break
    return result


def is_allowed(
    session: Session,
    *,
    user_id: uuid.UUID,
    action: str,
    territory_id: uuid.UUID,
    required_clearance: int,
    at: datetime | None = None,
) -> bool:
    return bool(
        matching_assignments(
            session,
            user_id=user_id,
            action=action,
            territory_id=territory_id,
            required_clearance=required_clearance,
            at=at,
        )
    )
