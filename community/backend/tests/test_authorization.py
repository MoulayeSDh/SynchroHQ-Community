import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.authorization.service import is_allowed
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


def test_permission_clearance_and_scope_are_all_required() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tenant_id = uuid.uuid4()
    with Session(engine) as session:
        country = Territory(
            id=uuid.uuid4(), tenant_id=tenant_id, code="MR", name="Test", type_code="COUNTRY"
        )
        north = Territory(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            code="N",
            name="North",
            type_code="WILAYA",
            parent_id=country.id,
        )
        south = Territory(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            code="S",
            name="South",
            type_code="WILAYA",
            parent_id=country.id,
        )
        commune = Territory(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            code="N1",
            name="Commune",
            type_code="COMMUNE",
            parent_id=north.id,
        )
        foreign = Territory(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            code="FOREIGN",
            name="Foreign tenant",
            type_code="WILAYA",
        )
        role = Role(tenant_id=tenant_id, code="REVIEWER", name="Reviewer")
        permission = Permission(code="reports:read")
        organization = Organization(tenant_id=tenant_id, code="ORG", name="Org", type_code="ADMIN")
        user = User(tenant_id=tenant_id, subject="reviewer", display_name="Reviewer")
        session.add_all(
            [country, north, south, commune, foreign, role, permission, organization, user]
        )
        session.flush()
        assignment = UserAssignment(
            user_id=user.id,
            organization_id=organization.id,
            role_id=role.id,
            clearance_level=2,
            valid_from=datetime.now(UTC),
        )
        session.add_all(
            [
                assignment,
                RolePermission(role_id=role.id, permission_id=permission.id),
            ]
        )
        session.flush()
        session.add(
            AssignmentScope(
                assignment_id=assignment.id, territory_id=north.id, coverage="DESCENDANTS"
            )
        )
        session.commit()

        assert is_allowed(
            session,
            user_id=user.id,
            action="reports:read",
            territory_id=commune.id,
            required_clearance=2,
        )
        assert not is_allowed(
            session,
            user_id=user.id,
            action="reports:read",
            territory_id=south.id,
            required_clearance=2,
        )
        assert not is_allowed(
            session,
            user_id=user.id,
            action="reports:read",
            territory_id=commune.id,
            required_clearance=3,
        )
        assert not is_allowed(
            session,
            user_id=user.id,
            action="reports:write",
            territory_id=commune.id,
            required_clearance=1,
        )
        assert not is_allowed(
            session,
            user_id=user.id,
            action="reports:read",
            territory_id=foreign.id,
            required_clearance=1,
        )
