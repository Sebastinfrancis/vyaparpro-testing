"""add inventory warehouse stock transfer tables

Revision ID: b7c8d9e0f1a2
Revises: 9f1c2d3e4a5b
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = '9f1c2d3e4a5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── warehouses ──────────────────────────────────────────────────
    if 'warehouses' not in existing:
        op.create_table(
            'warehouses',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('branch_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('branches.id'), nullable=True),
            sa.Column('warehouse_code', sa.String(20), nullable=False),
            sa.Column('warehouse_name', sa.String(100), nullable=False),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('city', sa.String(80), nullable=True),
            sa.Column('state', sa.String(80), nullable=True),
            sa.Column('pincode', sa.String(10), nullable=True),
            sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('capacity_sqft', sa.Numeric(12, 2), nullable=True),
            sa.Column('warehouse_type', sa.String(20), nullable=False, server_default='owned'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint('company_id', 'warehouse_code'),
        )
        op.create_index('ix_warehouses_company_id', 'warehouses', ['company_id'])
        op.create_index('ix_warehouses_branch_id', 'warehouses', ['branch_id'])

    # ── warehouse_zones ─────────────────────────────────────────────
    if 'warehouse_zones' not in existing:
        op.create_table(
            'warehouse_zones',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=False),
            sa.Column('zone_code', sa.String(20), nullable=False),
            sa.Column('zone_name', sa.String(60), nullable=False),
            sa.Column('zone_type', sa.String(20), nullable=False, server_default='storage'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('warehouse_id', 'zone_code'),
        )

    # ── inventory_stock ─────────────────────────────────────────────
    if 'inventory_stock' not in existing:
        op.create_table(
            'inventory_stock',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=False),
            sa.Column('zone_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_zones.id'), nullable=True),
            sa.Column('batch_no', sa.String(50), nullable=False, server_default=''),
            sa.Column('serial_no', sa.String(80), nullable=False, server_default=''),
            sa.Column('expiry_date', sa.Date(), nullable=True),
            sa.Column('mfg_date', sa.Date(), nullable=True),
            sa.Column('quantity', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('reserved_qty', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('cost_price', sa.Numeric(15, 2), nullable=False, server_default='0'),
            sa.Column('valuation_method', sa.String(10), nullable=False, server_default='FIFO'),
            sa.Column('barcode', sa.String(100), nullable=True),
            sa.Column('qr_data', sa.Text(), nullable=True),
            sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('product_id', 'warehouse_id', 'batch_no', 'serial_no',
                                 name='uq_stock_product_warehouse_batch_serial'),
        )
        op.create_index('ix_inventory_stock_company_id', 'inventory_stock', ['company_id'])
        op.create_index('ix_inventory_stock_warehouse_id', 'inventory_stock', ['warehouse_id'])
        op.create_index('ix_inventory_stock_product_id', 'inventory_stock', ['product_id'])

    # ── stock_movements ─────────────────────────────────────────────
    if 'stock_movements' not in existing:
        op.create_table(
            'stock_movements',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=False),
            sa.Column('zone_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouse_zones.id'), nullable=True),
            sa.Column('movement_type', sa.String(30), nullable=False),
            sa.Column('ref_type', sa.String(30), nullable=True),
            sa.Column('ref_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('ref_no', sa.String(50), nullable=True),
            sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
            sa.Column('cost_price', sa.Numeric(15, 2), nullable=True),
            sa.Column('batch_no', sa.String(50), nullable=True),
            sa.Column('serial_no', sa.String(80), nullable=True),
            sa.Column('expiry_date', sa.Date(), nullable=True),
            sa.Column('mfg_date', sa.Date(), nullable=True),
            sa.Column('narration', sa.Text(), nullable=True),
            sa.Column('movement_date', sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )
        op.create_index('ix_stock_movements_company_id', 'stock_movements', ['company_id'])
        op.create_index('ix_stock_movements_product_id', 'stock_movements', ['product_id'])
        op.create_index('ix_stock_movements_warehouse_id', 'stock_movements', ['warehouse_id'])
        op.create_index('ix_stock_movements_movement_date', 'stock_movements', ['movement_date'])

    # ── stock_adjustments ───────────────────────────────────────────
    if 'stock_adjustments' not in existing:
        op.create_table(
            'stock_adjustments',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('branch_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('branches.id'), nullable=True),
            sa.Column('adjustment_no', sa.String(30), nullable=False),
            sa.Column('adjustment_date', sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column('adjustment_type', sa.String(20), nullable=False, server_default='physical_count'),
            sa.Column('warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=False),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
            sa.Column('approved_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('company_id', 'adjustment_no'),
        )

    # ── stock_adjustment_items ──────────────────────────────────────
    if 'stock_adjustment_items' not in existing:
        op.create_table(
            'stock_adjustment_items',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('adjustment_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('stock_adjustments.id', ondelete='CASCADE'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('batch_no', sa.String(50), nullable=True),
            sa.Column('serial_no', sa.String(80), nullable=True),
            sa.Column('expiry_date', sa.Date(), nullable=True),
            sa.Column('system_qty', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('physical_qty', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('variance_qty', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('cost_price', sa.Numeric(15, 2), nullable=False, server_default='0'),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('display_order', sa.SmallInteger(), nullable=False, server_default='0'),
        )

    # ── stock_transfers ─────────────────────────────────────────────
    if 'stock_transfers' not in existing:
        op.create_table(
            'stock_transfers',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('transfer_no', sa.String(30), nullable=False),
            sa.Column('transfer_date', sa.Date(), nullable=False),
            sa.Column('from_warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=False),
            sa.Column('to_warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
            sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('narration', sa.Text(), nullable=True),
            sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('received_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('company_id', 'transfer_no'),
        )

    # ── stock_transfer_items ────────────────────────────────────────
    if 'stock_transfer_items' not in existing:
        op.create_table(
            'stock_transfer_items',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('transfer_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('stock_transfers.id', ondelete='CASCADE'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('batch_no', sa.String(50), nullable=True),
            sa.Column('serial_no', sa.String(80), nullable=True),
            sa.Column('expiry_date', sa.Date(), nullable=True),
            sa.Column('transfer_qty', sa.Numeric(12, 3), nullable=False),
            sa.Column('received_qty', sa.Numeric(12, 3), nullable=False, server_default='0'),
            sa.Column('cost_price', sa.Numeric(15, 2), nullable=False, server_default='0'),
        )

    # ── product_batches ─────────────────────────────────────────────
    if 'product_batches' not in existing:
        op.create_table(
            'product_batches',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('batch_no', sa.String(50), nullable=False),
            sa.Column('mfg_date', sa.Date(), nullable=True),
            sa.Column('expiry_date', sa.Date(), nullable=True),
            sa.Column('quantity_produced', sa.Numeric(12, 3), nullable=True),
            sa.Column('cost_price', sa.Numeric(15, 2), nullable=False, server_default='0'),
            sa.Column('barcode', sa.String(100), nullable=True),
            sa.Column('qr_code_data', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('product_id', 'batch_no'),
        )

    # ── serial_numbers ──────────────────────────────────────────────
    if 'serial_numbers' not in existing:
        op.create_table(
            'serial_numbers',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('serial_no', sa.String(80), nullable=False),
            sa.Column('batch_no', sa.String(50), nullable=True),
            sa.Column('warehouse_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('warehouses.id'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='in_stock'),
            sa.Column('purchase_date', sa.Date(), nullable=True),
            sa.Column('sale_date', sa.Date(), nullable=True),
            sa.Column('purchase_ref_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('sale_ref_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('sold_to_party_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('parties.id'), nullable=True),
            sa.Column('warranty_months', sa.SmallInteger(), nullable=True),
            sa.Column('warranty_expiry', sa.Date(), nullable=True),
            sa.Column('barcode', sa.String(100), nullable=True),
            sa.Column('qr_code_data', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint('product_id', 'serial_no'),
        )

    # ── barcode_labels ──────────────────────────────────────────────
    if 'barcode_labels' not in existing:
        op.create_table(
            'barcode_labels',
            sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
            sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('label_type', sa.String(20), nullable=False),
            sa.Column('ref_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('barcode_value', sa.String(200), nullable=False),
            sa.Column('barcode_type', sa.String(20), nullable=False, server_default='CODE128'),
            sa.Column('qr_data', sa.Text(), nullable=True),
            sa.Column('label_data', sa.dialects.postgresql.JSONB(), nullable=False, server_default='{}'),
            sa.Column('print_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_printed', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )

    # ── new permission codes for the warehouse / inventory module ───
    op.execute("""
        INSERT INTO permissions (id, perm_code, module, action, description)
        VALUES
            (uuid_generate_v4(), 'warehouse.create', 'warehouse', 'create', 'Create warehouses/stock points for a branch'),
            (uuid_generate_v4(), 'warehouse.read',   'warehouse', 'read',   'View warehouses'),
            (uuid_generate_v4(), 'warehouse.update', 'warehouse', 'update', 'Edit warehouse details'),
            (uuid_generate_v4(), 'warehouse.delete', 'warehouse', 'delete', 'Deactivate a warehouse'),
            (uuid_generate_v4(), 'inventory.read',   'inventory', 'read',   'View stock levels & valuation'),
            (uuid_generate_v4(), 'inventory.adjust', 'inventory', 'adjust', 'Create & post stock adjustments'),
            (uuid_generate_v4(), 'inventory.transfer', 'inventory', 'transfer', 'Create & dispatch inter-branch stock transfers'),
            (uuid_generate_v4(), 'inventory.transfer_receive', 'inventory', 'transfer_receive', 'Receive/cancel inter-branch stock transfers')
        ON CONFLICT (perm_code) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM permissions WHERE perm_code IN (
            'warehouse.create','warehouse.read','warehouse.update','warehouse.delete',
            'inventory.read','inventory.adjust','inventory.transfer','inventory.transfer_receive'
        );
    """)
    op.drop_table('barcode_labels')
    op.drop_table('serial_numbers')
    op.drop_table('product_batches')
    op.drop_table('stock_transfer_items')
    op.drop_table('stock_transfers')
    op.drop_table('stock_adjustment_items')
    op.drop_table('stock_adjustments')
    op.drop_table('stock_movements')
    op.drop_table('inventory_stock')
    op.drop_table('warehouse_zones')
    op.drop_table('warehouses')