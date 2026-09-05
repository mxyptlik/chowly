"""normalize menu categories and preparation destinations

Revision ID: a14c29d40b7e
Revises: 48f961b063ff
Create Date: 2026-08-31
"""

from typing import Sequence, Union
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "a14c29d40b7e"
down_revision: Union[str, None] = "48f961b063ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("location_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_menu_category_location",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_categories")),
        sa.UniqueConstraint("tenant_id", "location_id", "id", name="uq_menu_category_scope_id"),
        sa.UniqueConstraint("tenant_id", "location_id", "name", name="uq_menu_category_name"),
    )
    op.create_index(op.f("ix_menu_categories_location_id"), "menu_categories", ["location_id"])

    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("queue_destination", sa.String(length=10), nullable=True)
        )

    # Python-side UUID5 backfill is deterministic and works on PostgreSQL and
    # SQLite; it intentionally avoids dialect-only hashing functions.
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT DISTINCT tenant_id, location_id, category "
            "FROM menu_items ORDER BY tenant_id, location_id, category"
        )
    ).mappings()
    for row in rows:
        category_id = str(
            uuid5(
                NAMESPACE_URL,
                f"chowly:{row['tenant_id']}:{row['location_id']}:{row['category']}",
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO menu_categories "
                "(id, tenant_id, location_id, name, sort_order, is_active, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :location_id, :name, 0, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": category_id,
                "tenant_id": row["tenant_id"],
                "location_id": row["location_id"],
                "name": row["category"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE menu_items SET category_id = :category_id, "
                "queue_destination = CASE WHEN item_type = 'DRINK' THEN 'BAR' ELSE 'KITCHEN' END "
                "WHERE tenant_id = :tenant_id AND location_id = :location_id AND category = :name"
            ),
            {
                "category_id": category_id,
                "tenant_id": row["tenant_id"],
                "location_id": row["location_id"],
                "name": row["category"],
            },
        )
    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.alter_column("category_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column(
            "queue_destination",
            existing_type=sa.String(length=10),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_menu_item_queue_destination",
            "queue_destination IN ('KITCHEN', 'BAR')",
        )
        batch_op.create_index(op.f("ix_menu_items_category_id"), ["category_id"])
        batch_op.create_foreign_key(
            "fk_menu_item_category",
            "menu_categories",
            ["tenant_id", "location_id", "category_id"],
            ["tenant_id", "location_id", "id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("menu_items") as batch_op:
        batch_op.drop_constraint("fk_menu_item_category", type_="foreignkey")
        batch_op.drop_constraint("ck_menu_item_queue_destination", type_="check")
        batch_op.drop_index(op.f("ix_menu_items_category_id"))
        batch_op.drop_column("queue_destination")
        batch_op.drop_column("category_id")
    op.drop_index(op.f("ix_menu_categories_location_id"), table_name="menu_categories")
    op.drop_table("menu_categories")
