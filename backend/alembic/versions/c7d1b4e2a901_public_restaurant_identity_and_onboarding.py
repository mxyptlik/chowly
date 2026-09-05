"""public restaurant identity and onboarding lifecycle

Revision ID: c7d1b4e2a901
Revises: fa129fbb3c17
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d1b4e2a901"
down_revision: Union[str, None] = "fa129fbb3c17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slug(value: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "restaurant")[:160]


def upgrade() -> None:
    lifecycle = sa.Enum("PENDING_SETUP", "ACTIVE", "SUSPENDED", name="tenant_lifecycle", native_enum=False, create_constraint=True)
    op.add_column("tenants", sa.Column("slug", sa.String(length=180), nullable=True))
    op.add_column("tenants", sa.Column("lifecycle", lifecycle, nullable=False, server_default="ACTIVE"))
    op.add_column("tenants", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("tenants", sa.Column("cover_image_url", sa.String(length=1000), nullable=True))
    op.add_column("locations", sa.Column("slug", sa.String(length=180), nullable=True))
    op.add_column("locations", sa.Column("cover_image_url", sa.String(length=1000), nullable=True))
    op.add_column("menu_items", sa.Column("image_url", sa.String(length=1000), nullable=True))

    bind = op.get_bind()
    used_tenants: set[str] = set()
    for row in bind.execute(sa.text("SELECT id, name FROM tenants ORDER BY id")).mappings():
        base, candidate, suffix = _slug(row["name"]), _slug(row["name"]), 2
        while candidate in used_tenants:
            candidate = f"{base[:150]}-{suffix}"; suffix += 1
        used_tenants.add(candidate)
        bind.execute(sa.text("UPDATE tenants SET slug = :slug WHERE id = :id"), {"slug": candidate, "id": row["id"]})
    for tenant in bind.execute(sa.text("SELECT id FROM tenants")).mappings():
        used: set[str] = set()
        for row in bind.execute(sa.text("SELECT id, name FROM locations WHERE tenant_id = :tenant_id ORDER BY id"), {"tenant_id": tenant["id"]}).mappings():
            base, candidate, suffix = _slug(row["name"]), _slug(row["name"]), 2
            while candidate in used:
                candidate = f"{base[:150]}-{suffix}"; suffix += 1
            used.add(candidate)
            bind.execute(sa.text("UPDATE locations SET slug = :slug WHERE id = :id"), {"slug": candidate, "id": row["id"]})

    with op.batch_alter_table("tenants") as batch:
        batch.alter_column("slug", nullable=False)
        batch.create_unique_constraint("uq_tenants_slug", ["slug"])
        batch.create_index("ix_tenants_slug", ["slug"])
    with op.batch_alter_table("locations") as batch:
        batch.alter_column("slug", nullable=False)
        batch.create_unique_constraint("uq_location_tenant_slug", ["tenant_id", "slug"])
        batch.create_index("ix_locations_slug", ["slug"])


def downgrade() -> None:
    with op.batch_alter_table("locations") as batch:
        batch.drop_index("ix_locations_slug")
        batch.drop_constraint("uq_location_tenant_slug", type_="unique")
        batch.drop_column("cover_image_url")
        batch.drop_column("slug")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_index("ix_tenants_slug")
        batch.drop_constraint("uq_tenants_slug", type_="unique")
        batch.drop_column("cover_image_url")
        batch.drop_column("description")
        batch.drop_column("lifecycle")
        batch.drop_column("slug")
    op.drop_column("menu_items", "image_url")
