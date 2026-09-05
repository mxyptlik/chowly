"""reservation customer policy and QR verification pass

Revision ID: d8e2f1a4c903
Revises: c7d1b4e2a901
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d8e2f1a4c903"
down_revision: Union[str, None] = "c7d1b4e2a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("locations", sa.Column("customer_edits_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("locations", sa.Column("customer_edit_cutoff_minutes", sa.Integer(), nullable=False, server_default="120"))
    op.add_column("locations", sa.Column("customer_cancellations_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("locations", sa.Column("customer_cancellation_cutoff_minutes", sa.Integer(), nullable=False, server_default="30"))
    # SQLite cannot ALTER a table to add a unique constraint. Batch mode uses a
    # copy-and-swap table rewrite there while emitting ordinary ALTER on Postgres.
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("qr_pass_token_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("checked_in_by_id", sa.String(length=36), nullable=True))
        batch.create_unique_constraint("uq_reservations_qr_pass_token_hash", ["qr_pass_token_hash"])

def downgrade() -> None:
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("uq_reservations_qr_pass_token_hash", type_="unique")
        batch.drop_column("checked_in_by_id")
        batch.drop_column("checked_in_at")
        batch.drop_column("qr_pass_token_hash")
    op.drop_column("locations", "customer_cancellation_cutoff_minutes")
    op.drop_column("locations", "customer_cancellations_enabled")
    op.drop_column("locations", "customer_edit_cutoff_minutes")
    op.drop_column("locations", "customer_edits_enabled")
