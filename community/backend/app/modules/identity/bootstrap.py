"""One-time, interactive bootstrap for an empty Community installation."""

import argparse
import getpass
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.identity.models import BootstrapState, Tenant, UserCredential
from app.modules.identity.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


@dataclass(frozen=True)
class BootstrapInput:
    tenant_code: str
    tenant_name: str
    admin_identifier: str
    admin_name: str
    root_territory_name: str
    organization_name: str


def bootstrap(session: Session, values: BootstrapInput, password: str) -> Tenant:
    """Atomically create only the first tenant; never overwrite an existing installation."""
    code = values.tenant_code.strip().upper()
    identifier = values.admin_identifier.strip().casefold()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,63}", code):
        raise ValueError("Invalid tenant code")
    if not 3 <= len(identifier) <= 255 or any(char.isspace() for char in identifier):
        raise ValueError("Invalid administrator identifier")
    for name in (values.tenant_name, values.admin_name, values.root_territory_name,
                 values.organization_name):
        if not name.strip() or len(name) > 255:
            raise ValueError("Invalid name")
    password_hash = hash_password(password)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.connection().exec_driver_sql("SELECT pg_advisory_xact_lock(74591022)")
    if (
        session.get(BootstrapState, 1) is not None
        or session.scalar(select(User.id).limit(1)) is not None
        or session.scalar(select(Tenant.id).limit(1)) is not None
        or session.scalar(select(Territory.id).limit(1)) is not None
        or session.scalar(select(Organization.id).limit(1)) is not None
    ):
        raise ValueError("Installation already initialized")
    permissions = list(session.scalars(select(Permission)))
    if not permissions:
        raise ValueError("Apply database migrations before bootstrap")
    now = datetime.now(UTC)
    tenant = Tenant(code=code, name=values.tenant_name.strip())
    session.add(tenant)
    session.flush()
    territory = Territory(
        tenant_id=tenant.id, code="ROOT", name=values.root_territory_name.strip(),
        type_code="ROOT",
    )
    organization = Organization(
        tenant_id=tenant.id, code="ADMIN", name=values.organization_name.strip(),
        type_code="OPERATOR",
    )
    role = Role(tenant_id=tenant.id, code="ADMIN", name="Super Administrator")
    user = User(tenant_id=tenant.id, subject=identifier, display_name=values.admin_name.strip())
    session.add_all([territory, organization, role, user])
    session.flush()
    assignment = UserAssignment(
        user_id=user.id, organization_id=organization.id, role_id=role.id,
        clearance_level=100, valid_from=now,
    )
    session.add(assignment)
    session.flush()
    session.add_all([
        UserCredential(user_id=user.id, password_hash=password_hash, password_changed_at=now),
        AssignmentScope(assignment_id=assignment.id, territory_id=territory.id,
                        coverage="DESCENDANTS"),
        BootstrapState(id=1, tenant_id=tenant.id, completed_at=now),
        *(RolePermission(role_id=role.id, permission_id=p.id) for p in permissions),
    ])
    session.flush()
    return tenant


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize an empty SynchroHQ Community database")
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--admin-identifier", required=True)
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--root-territory-name", required=True)
    parser.add_argument("--organization-name", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "production":
        parser.error("Bootstrap requires APP_ENV=production")
    if settings.auth_jwt_secret == "development-only-change-me-32-chars":
        parser.error("Configure a unique AUTH_JWT_SECRET first")
    password = getpass.getpass("Administrator password: ")
    if password != getpass.getpass("Confirm administrator password: "):
        parser.error("Passwords do not match")
    values = BootstrapInput(
        tenant_code=args.tenant_code, tenant_name=args.tenant_name,
        admin_identifier=args.admin_identifier, admin_name=args.admin_name,
        root_territory_name=args.root_territory_name,
        organization_name=args.organization_name,
    )
    try:
        with SessionLocal.begin() as session:
            tenant = bootstrap(session, values, password)
    except ValueError as exc:
        print(f"Bootstrap refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Community initialized for tenant {tenant.code} ({tenant.id})")


if __name__ == "__main__":
    main()
