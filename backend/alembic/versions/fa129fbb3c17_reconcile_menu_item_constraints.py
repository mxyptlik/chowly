"""reconcile menu item constraints

Revision ID: fa129fbb3c17
Revises: b3c6e0d718f2
Create Date: 2026-08-31 21:54:44.871650
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fa129fbb3c17'
down_revision: Union[str, None] = 'b3c6e0d718f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode keeps this corrective migration portable to SQLite, which
    # rebuilds a table for ALTER COLUMN operations. PostgreSQL executes the
    # same intent transactionally without losing existing menu rows.
    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.alter_column(
            "category_id",
            existing_type=sa.VARCHAR(length=36),
            nullable=True,
        )
        batch_op.alter_column(
            "queue_destination",
            existing_type=sa.VARCHAR(length=10),
            type_=sa.Enum(
                "KITCHEN",
                "BAR",
                name="menu_queue_destination",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.alter_column(
            "queue_destination",
            existing_type=sa.Enum(
                "KITCHEN",
                "BAR",
                name="menu_queue_destination",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.VARCHAR(length=10),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "category_id",
            existing_type=sa.VARCHAR(length=36),
            nullable=False,
        )
