"""store only digests for public reservation status tokens

Revision ID: b3c6e0d718f2
Revises: a14c29d40b7e
Create Date: 2026-08-31
"""

from hashlib import sha256
from secrets import token_urlsafe
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c6e0d718f2"
down_revision: Union[str, None] = "a14c29d40b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing reservations receive a random digest.  Their raw token cannot be
    # reconstructed, which is intentional: no historic public capability is
    # silently manufactured from an identifier or phone number.
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.add_column(sa.Column("public_access_token_hash", sa.String(length=64), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM reservations")).mappings()
    for row in rows:
        digest = sha256(token_urlsafe(32).encode("utf-8")).hexdigest()
        connection.execute(
            sa.text(
                "UPDATE reservations SET public_access_token_hash = :digest WHERE id = :id"
            ),
            {"digest": digest, "id": row["id"]},
        )

    with op.batch_alter_table("reservations") as batch_op:
        batch_op.alter_column(
            "public_access_token_hash",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_reservation_public_access_token_hash",
            ["public_access_token_hash"],
        )


def downgrade() -> None:
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.drop_constraint("uq_reservation_public_access_token_hash", type_="unique")
        batch_op.drop_column("public_access_token_hash")
