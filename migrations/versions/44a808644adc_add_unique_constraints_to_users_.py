"""add unique constraints to users username and email

Revision ID: 44a808644adc
Revises: b0725bc519d7
Create Date: 2026-08-15 11:09:52.973728

Hand-reviewed: autogenerate produced this via `batch_alter_table` with
unnamed constraints (SQLite-style table recreation, unneeded on PostgreSQL,
and `None` constraint names that would break `downgrade()`). Rewritten as
plain `create_unique_constraint`/`drop_constraint` calls with explicit
names. This revision only adds `users_username_key` and `users_email_key`;
the existing case-insensitive functional indexes (`uq_users_username_ci`,
`uq_users_email_ci`) from the baseline revision are untouched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '44a808644adc'
down_revision = 'b0725bc519d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint('users_email_key', 'users', ['email'])
    op.create_unique_constraint('users_username_key', 'users', ['username'])


def downgrade():
    op.drop_constraint('users_username_key', 'users', type_='unique')
    op.drop_constraint('users_email_key', 'users', type_='unique')
