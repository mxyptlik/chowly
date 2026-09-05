"""extend reservation status for check in

Revision ID: e9f3b2c5d104
Revises: d8e2f1a4c903
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e9f3b2c5d104"
down_revision: Union[str, None] = "d8e2f1a4c903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    status = sa.Enum("REQUESTED", "CONFIRMED", "REJECTED", "CANCELLED", "CHECKED_IN", "SEATED", name="reservation_status", native_enum=False, create_constraint=True)
    old_status = sa.Enum("REQUESTED", "CONFIRMED", "REJECTED", "CANCELLED", "SEATED", name="reservation_status", native_enum=False, create_constraint=True)
    if op.get_bind().dialect.name == "sqlite":
        # SQLite has no ALTER TABLE DROP CONSTRAINT. Batch mode rewrites the
        # table and replaces the old enum check with the expanded constraint.
        with op.batch_alter_table("reservations") as batch:
            batch.alter_column("status", existing_type=old_status, type_=status, existing_nullable=False)
        return
    op.execute("ALTER TABLE reservations DROP CONSTRAINT IF EXISTS ck_reservations_reservation_status")
    # ``create_constraint=True`` on this non-native Enum causes Alembic to add
    # the convention-named check constraint during ``alter_column``.  Adding it
    # again explicitly raises PostgreSQL ``DuplicateObject`` on a fresh upgrade.
    op.alter_column("reservations", "status", existing_type=sa.String(length=9), type_=status, existing_nullable=False)

def downgrade() -> None:
    status = sa.Enum("REQUESTED", "CONFIRMED", "REJECTED", "CANCELLED", "CHECKED_IN", "SEATED", name="reservation_status", native_enum=False, create_constraint=True)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("reservations") as batch:
            batch.alter_column("status", existing_type=status, type_=sa.String(length=9), existing_nullable=False)
        return
    op.alter_column("reservations", "status", existing_type=status, type_=sa.String(length=9), existing_nullable=False)
