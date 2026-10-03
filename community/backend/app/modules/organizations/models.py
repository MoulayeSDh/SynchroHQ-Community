import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    type_code: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrganizationTerritory(Base):
    __tablename__ = "organization_territories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), primary_key=True
    )
    territory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("territories.id"), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(32), primary_key=True)
