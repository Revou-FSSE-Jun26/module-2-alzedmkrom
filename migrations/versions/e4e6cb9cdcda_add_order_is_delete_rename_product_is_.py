"""add order is_delete, rename product is_active to is_delete

Revision ID: e4e6cb9cdcda
Revises: 48a1dad68d30
Create Date: 2026-08-22 18:46:17.603670

Hand-reviewed: autogenerate wrapped both tables in `batch_alter_table`
(SQLite-style table recreation, unneeded on PostgreSQL, same as every
earlier revision in this history) and, for `products`, generated a bare
`drop_column('is_active')` with no data carried forward -- that would
silently reset every product to `is_delete = false` regardless of its
actual prior `is_active` value.

Rewritten as three plain steps for `products`:
  1. Add `is_delete` as NULLable, no default (so the next step can tell
     which rows still need a value).
  2. Backfill it from the *inverse* of the existing `is_active` column via
     `UPDATE ... SET is_delete = NOT is_active`, then set NOT NULL.
  3. Drop `is_active`.

`orders.is_delete` has no prior column to invert from, so it is just a
plain `add_column` with `server_default=false` (nothing was ever
soft-deleted before this column existed).

`downgrade()` mirrors this: recreates `products.is_active` from the inverse
of `is_delete`, then drops both `is_delete` columns.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4e6cb9cdcda'
down_revision = '48a1dad68d30'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'orders',
        sa.Column(
            'is_delete',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # Step 1: add as nullable, no default, so every existing row is
    # visibly unset until the backfill below runs.
    op.add_column('products', sa.Column('is_delete', sa.Boolean(), nullable=True))

    # Step 2: backfill from the inverse of the column being replaced.
    op.execute('UPDATE products SET is_delete = NOT is_active')

    # Now safe to lock it down: NOT NULL + a server default for future inserts.
    op.alter_column(
        'products',
        'is_delete',
        nullable=False,
        server_default=sa.text('false'),
    )

    # Step 3: the old column's job is done.
    op.drop_column('products', 'is_active')


def downgrade():
    op.add_column('products', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.execute('UPDATE products SET is_active = NOT is_delete')
    op.alter_column(
        'products',
        'is_active',
        nullable=False,
        server_default=sa.text('true'),
    )
    op.drop_column('products', 'is_delete')

    op.drop_column('orders', 'is_delete')
