"""add role to users

Revision ID: 67d9a832861f
Revises: 44a808644adc
Create Date: 2026-08-15 11:15:40.259139

Hand-reviewed: autogenerate wrapped the change in `batch_alter_table`
(SQLite-style table recreation, unneeded on PostgreSQL, same as the earlier
unique-constraints revision). Rewritten as a plain `add_column`/`drop_column`
pair. The `server_default=sa.text("'CUSTOMER'")` on `add_column` is the part
that matters: it makes PostgreSQL backfill all existing rows with
`'CUSTOMER'` in the same statement that adds the `NOT NULL` column, so no
separate `UPDATE` is needed and no existing column values are touched.
`downgrade()` drops the column, restoring the prior schema.

This is the head revision: an earlier fourth revision that swapped the
default to `'USER'` was written, applied, then deliberately reverted
(`flask db downgrade` back to this revision, followed by an `UPDATE`
restoring the affected rows to `'CUSTOMER'`) so the history stays at three
revisions with `'CUSTOMER'` as the single source of truth.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '67d9a832861f'
down_revision = '44a808644adc'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'role',
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'CUSTOMER'"),
        ),
    )


def downgrade():
    op.drop_column('users', 'role')
