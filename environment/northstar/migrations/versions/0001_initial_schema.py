"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-26 07:48:44.122806
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('admin_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_users')),
    sa.UniqueConstraint('username', name=op.f('uq_admin_users_username'))
    )
    op.create_table('brands',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brands')),
    sa.UniqueConstraint('name', name=op.f('uq_brands_name')),
    sa.UniqueConstraint('slug', name=op.f('uq_brands_slug'))
    )
    op.create_table('categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name=op.f('ck_categories_not_own_parent')),
    sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], name=op.f('fk_categories_parent_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('slug', name=op.f('uq_categories_slug'))
    )
    op.create_index(op.f('ix_categories_parent_id'), 'categories', ['parent_id'], unique=False)
    op.create_table('customers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('level', sa.String(length=20), server_default='retail', nullable=False),
    sa.Column('phone', sa.String(length=40), server_default='', nullable=False),
    sa.Column('address_line1', sa.String(length=200), server_default='', nullable=False),
    sa.Column('address_line2', sa.String(length=200), server_default='', nullable=False),
    sa.Column('city', sa.String(length=100), server_default='', nullable=False),
    sa.Column('state', sa.String(length=50), server_default='', nullable=False),
    sa.Column('postal_code', sa.String(length=20), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("level IN ('retail', 'contractor', 'vip')", name=op.f('ck_customers_customer_level')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('email', name=op.f('uq_customers_email'))
    )
    op.create_table('site_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('announcement_text', sa.Text(), server_default='', nullable=False),
    sa.Column('announcement_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name=op.f('ck_site_settings_singleton')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_settings'))
    )
    op.create_table('carts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('guest_token', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'checking_out', 'completed', 'merged')", name=op.f('ck_carts_cart_status')),
    sa.CheckConstraint('customer_id IS NOT NULL OR guest_token IS NOT NULL', name=op.f('ck_carts_has_owner')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_carts_customer_id_customers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_carts')),
    sa.UniqueConstraint('guest_token', name=op.f('uq_carts_guest_token'))
    )
    op.create_index(op.f('ix_carts_customer_id'), 'carts', ['customer_id'], unique=False)
    op.create_index('uq_carts_one_open_per_customer', 'carts', ['customer_id'], unique=True, postgresql_where=sa.text("status IN ('active', 'checking_out') AND customer_id IS NOT NULL"))
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('brand_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('msrp', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('map_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('map_enforced', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('inventory_qty', sa.Integer(), server_default='0', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_new', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('NOT map_enforced OR map_price IS NOT NULL', name=op.f('ck_products_enforced_map_has_price')),
    sa.CheckConstraint('inventory_qty >= 0', name=op.f('ck_products_inventory_non_negative')),
    sa.CheckConstraint('map_price IS NULL OR map_price >= 0', name=op.f('ck_products_map_non_negative')),
    sa.CheckConstraint('msrp >= 0 AND price >= 0 AND cost >= 0', name=op.f('ck_products_prices_non_negative')),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], name=op.f('fk_products_brand_id_brands')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products')),
    sa.UniqueConstraint('sku', name=op.f('uq_products_sku'))
    )
    op.create_index(op.f('ix_products_brand_id'), 'products', ['brand_id'], unique=False)
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_table('cart_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cart_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_cart_items_quantity_positive')),
    sa.ForeignKeyConstraint(['cart_id'], ['carts.id'], name=op.f('fk_cart_items_cart_id_carts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_cart_items_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cart_items')),
    sa.UniqueConstraint('cart_id', 'product_id', name='uq_cart_items_cart_product')
    )
    op.create_table('checkout_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('cart_id', sa.Integer(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payment_reference', sa.String(length=64), nullable=False),
    sa.Column('card_last4', sa.String(length=4), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('address_line1', sa.String(length=200), nullable=False),
    sa.Column('address_line2', sa.String(length=200), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=50), nullable=False),
    sa.Column('postal_code', sa.String(length=20), nullable=False),
    sa.Column('customer_level', sa.String(length=20), nullable=True),
    sa.Column('quote_lines', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('shipping', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('tax', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('reserved_lines', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('failure_code', sa.String(length=50), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("customer_level IN ('retail', 'contractor', 'vip')", name=op.f('ck_checkout_attempts_attempt_level')),
    sa.CheckConstraint("status IN ('authorizing', 'authorized', 'capturing', 'voiding', 'completed', 'failed')", name=op.f('ck_checkout_attempts_attempt_status')),
    sa.ForeignKeyConstraint(['cart_id'], ['carts.id'], name=op.f('fk_checkout_attempts_cart_id_carts')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_checkout_attempts_customer_id_customers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_checkout_attempts')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_checkout_attempts_idempotency_key')),
    sa.UniqueConstraint('payment_reference', name=op.f('uq_checkout_attempts_payment_reference'))
    )
    op.create_index(op.f('ix_checkout_attempts_cart_id'), 'checkout_attempts', ['cart_id'], unique=False)
    op.create_index(op.f('ix_checkout_attempts_customer_id'), 'checkout_attempts', ['customer_id'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='completed', nullable=False),
    sa.Column('cart_id', sa.Integer(), nullable=False),
    sa.Column('checkout_attempt_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('customer_level', sa.String(length=20), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('address_line1', sa.String(length=200), nullable=False),
    sa.Column('address_line2', sa.String(length=200), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=50), nullable=False),
    sa.Column('postal_code', sa.String(length=20), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('shipping', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('tax', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('payment_reference', sa.String(length=64), nullable=False),
    sa.Column('card_last4', sa.String(length=4), nullable=False),
    sa.Column('placed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("customer_level IN ('retail', 'contractor', 'vip')", name=op.f('ck_orders_order_level')),
    sa.CheckConstraint("status = 'completed'", name=op.f('ck_orders_status_completed')),
    sa.CheckConstraint('total = subtotal + shipping + tax', name=op.f('ck_orders_total_consistent')),
    sa.ForeignKeyConstraint(['cart_id'], ['carts.id'], name=op.f('fk_orders_cart_id_carts')),
    sa.ForeignKeyConstraint(['checkout_attempt_id'], ['checkout_attempts.id'], name=op.f('fk_orders_checkout_attempt_id_checkout_attempts')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_orders_customer_id_customers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('cart_id', name=op.f('uq_orders_cart_id')),
    sa.UniqueConstraint('checkout_attempt_id', name=op.f('uq_orders_checkout_attempt_id')),
    sa.UniqueConstraint('payment_reference', name=op.f('uq_orders_payment_reference'))
    )
    op.create_index(op.f('ix_orders_customer_id'), 'orders', ['customer_id'], unique=False)
    op.create_table('order_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('product_name', sa.String(length=200), nullable=False),
    sa.Column('brand_name', sa.String(length=100), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.CheckConstraint('line_total = unit_price * quantity', name=op.f('ck_order_lines_line_total_consistent')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_order_lines_quantity_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_lines_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_order_lines_product_id_products'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_lines'))
    )
    op.create_index(op.f('ix_order_lines_order_id'), 'order_lines', ['order_id'], unique=False)

    # Singleton homepage-content row.
    op.execute("INSERT INTO site_settings (id, announcement_text, announcement_active) VALUES (1, '', false)")


def downgrade() -> None:
    op.drop_index(op.f('ix_order_lines_order_id'), table_name='order_lines')
    op.drop_table('order_lines')
    op.drop_index(op.f('ix_orders_customer_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_checkout_attempts_customer_id'), table_name='checkout_attempts')
    op.drop_index(op.f('ix_checkout_attempts_cart_id'), table_name='checkout_attempts')
    op.drop_table('checkout_attempts')
    op.drop_table('cart_items')
    op.drop_index(op.f('ix_products_category_id'), table_name='products')
    op.drop_index(op.f('ix_products_brand_id'), table_name='products')
    op.drop_table('products')
    op.drop_index('uq_carts_one_open_per_customer', table_name='carts', postgresql_where=sa.text("status IN ('active', 'checking_out') AND customer_id IS NOT NULL"))
    op.drop_index(op.f('ix_carts_customer_id'), table_name='carts')
    op.drop_table('carts')
    op.drop_table('site_settings')
    op.drop_table('customers')
    op.drop_index(op.f('ix_categories_parent_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_table('brands')
    op.drop_table('admin_users')
