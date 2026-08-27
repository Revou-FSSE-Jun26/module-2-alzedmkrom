"""add is_active to products

Revision ID: 48a1dad68d30
Revises: 67d9a832861f
Create Date: 2026-08-21 00:13:35.584149

Hand-reviewed: autogenerate wrapped the change in `batch_alter_table`
(SQLite-style table recreation, unneeded on PostgreSQL, same as the two
earlier revisions in this history). Rewritten as a plain `add_column`/
`drop_column` pair. The `server_default=sa.text("true")` on `add_column` is
the part that matters: it makes PostgreSQL backfill all 10 existing product
rows with `true` in the same statement that adds the `NOT NULL` column, so
no separate `UPDATE` is needed and no existing column values are touched.

This backs the soft-delete behavior in `DELETE /products/<id>`: a product
whose order history is entirely finalized is deactivated (`is_active =
false`) instead of removed, since `order_items.product_id` has `ON DELETE
RESTRICT` and would reject a real row deletion regardless of the
referencing orders' status. `downgrade()` drops the column, restoring the
prior schema.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '48a1dad68d30'
down_revision = '67d9a832861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'products',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
    )


def downgrade():
    op.drop_column('products', 'is_active')
