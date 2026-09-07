"""add delayed order state and delay metadata

Revision ID: f1a4c6d8e205
Revises: e9f3b2c5d104
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a4c6d8e205"
down_revision: Union[str, None] = "e9f3b2c5d104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

old_status = sa.Enum("SUBMITTED", "PREPARING", "READY_FOR_SERVICE", "SERVED", "PAID", "CANCELLED", name="order_status", native_enum=False, create_constraint=True)
new_status = sa.Enum("SUBMITTED", "PREPARING", "DELAYED", "READY_FOR_SERVICE", "SERVED", "PAID", "CANCELLED", name="order_status", native_enum=False, create_constraint=True)


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("status", existing_type=old_status, type_=new_status, existing_nullable=False, existing_server_default="SUBMITTED")
        batch_op.add_column(sa.Column("delay_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("delayed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute(sa.text("UPDATE orders SET status = 'PREPARING' WHERE status = 'DELAYED'"))
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("delayed_at")
        batch_op.drop_column("delay_reason")
        batch_op.alter_column("status", existing_type=new_status, type_=old_status, existing_nullable=False, existing_server_default="SUBMITTED")
