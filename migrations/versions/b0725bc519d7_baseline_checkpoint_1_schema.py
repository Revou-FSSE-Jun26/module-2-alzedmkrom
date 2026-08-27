"""baseline: checkpoint 1 schema

Revision ID: b0725bc519d7
Revises: 
Create Date: 2026-08-15 10:58:02.492478

Hand-reviewed against schema.sql. Autogenerate, run against the already
populated ``revoshop_db``, only detected a diff for the plain ``unique=True``
declarations on ``users.username``/``users.email`` (that belongs to the later
"unique constraint" revision, not this baseline) and produced no
``create_table`` operations at all, since the five tables already exist and
match the models.

This revision is corrected by hand to describe the Checkpoint 1 schema as it
exists today: the five tables, the two case-insensitive unique indexes, and
the three foreign-key indexes, and nothing else. It is not run against the
populated database; instead it is stamped (task 6.2) so a reviewer starting
from an empty database can still ``flask db upgrade`` to the same schema.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b0725bc519d7'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # --- users ---------------------------------------------------------
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    # Case-insensitive uniqueness for usernames and email addresses.
    op.create_index('uq_users_username_ci', 'users', [sa.text('lower(username)')], unique=True)
    op.create_index('uq_users_email_ci', 'users', [sa.text('lower(email)')], unique=True)

    # --- categories ------------------------------------------------------
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
    )

    # --- products ---------------------------------------------------------
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(precision=11, scale=2), nullable=False),
        sa.Column('stock_quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['category_id'], ['categories.id'],
            name='fk_products_category', ondelete='RESTRICT',
        ),
        sa.CheckConstraint('price >= 0', name='products_price_check'),
        sa.CheckConstraint('stock_quantity >= 0', name='products_stock_quantity_check'),
    )
    # PostgreSQL does not automatically index foreign-key columns.
    op.create_index('idx_products_category_id', 'products', ['category_id'])

    # --- orders ---------------------------------------------------------
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('total_price', sa.Numeric(precision=14, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=75), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name='fk_orders_user', ondelete='RESTRICT',
        ),
        sa.CheckConstraint('total_price >= 0', name='orders_total_price_check'),
    )
    op.create_index('idx_orders_user_id', 'orders', ['user_id'])

    # --- order_items (association table) ---------------------------------
    op.create_table(
        'order_items',
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ['order_id'], ['orders.id'],
            name='fk_items_order', ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['product_id'], ['products.id'],
            name='fk_items_product', ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('order_id', 'product_id'),
        sa.CheckConstraint('quantity > 0', name='order_items_quantity_check'),
        sa.CheckConstraint('unit_price >= 0', name='order_items_unit_price_check'),
    )
    # order_items.order_id is already covered by the composite primary key.
    op.create_index('idx_order_items_product_id', 'order_items', ['product_id'])


def downgrade():
    op.drop_index('idx_order_items_product_id', table_name='order_items')
    op.drop_table('order_items')

    op.drop_index('idx_orders_user_id', table_name='orders')
    op.drop_table('orders')

    op.drop_index('idx_products_category_id', table_name='products')
    op.drop_table('products')

    op.drop_table('categories')

    op.drop_index('uq_users_email_ci', table_name='users')
    op.drop_index('uq_users_username_ci', table_name='users')
    op.drop_table('users')
