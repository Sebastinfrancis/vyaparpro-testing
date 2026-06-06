-- VyaparPro PostgreSQL Bootstrap
-- Runs once on first container start via docker-entrypoint-initdb.d

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Trigram indexes for fast ILIKE search (applied after Alembic creates tables)
-- These are created by Alembic migrations; this file just ensures extensions exist.

-- Seed GST rates (idempotent)
INSERT INTO gst_rates (id, rate_name, total_rate, cgst_rate, sgst_rate, igst_rate, cess_rate, is_active)
VALUES
  (uuid_generate_v4(), 'Exempt',   0,   0,    0,    0,   0, TRUE),
  (uuid_generate_v4(), 'GST 5%',   5,   2.5,  2.5,  5,   0, TRUE),
  (uuid_generate_v4(), 'GST 12%', 12,   6,    6,   12,   0, TRUE),
  (uuid_generate_v4(), 'GST 18%', 18,   9,    9,   18,   0, TRUE),
  (uuid_generate_v4(), 'GST 28%', 28,  14,   14,   28,   0, TRUE)
ON CONFLICT (total_rate) DO NOTHING;

-- Seed Units of Measure
INSERT INTO units_of_measure (id, uom_code, uom_name, conversion_factor, is_active)
VALUES
  (uuid_generate_v4(), 'PCS',   'Pieces',          1,    TRUE),
  (uuid_generate_v4(), 'KG',    'Kilograms',        1,    TRUE),
  (uuid_generate_v4(), 'G',     'Grams',            0.001,TRUE),
  (uuid_generate_v4(), 'LTR',   'Litres',           1,    TRUE),
  (uuid_generate_v4(), 'ML',    'Millilitres',      0.001,TRUE),
  (uuid_generate_v4(), 'MTR',   'Metres',           1,    TRUE),
  (uuid_generate_v4(), 'CM',    'Centimetres',      0.01, TRUE),
  (uuid_generate_v4(), 'BOX',   'Box',              1,    TRUE),
  (uuid_generate_v4(), 'PACK',  'Pack',             1,    TRUE),
  (uuid_generate_v4(), 'SET',   'Set',              1,    TRUE),
  (uuid_generate_v4(), 'PAIR',  'Pair',             1,    TRUE),
  (uuid_generate_v4(), 'NOS',   'Numbers',          1,    TRUE),
  (uuid_generate_v4(), 'ROLL',  'Roll',             1,    TRUE),
  (uuid_generate_v4(), 'SQ_MT', 'Square Metres',    1,    TRUE),
  (uuid_generate_v4(), 'CU_MT', 'Cubic Metres',     1,    TRUE),
  (uuid_generate_v4(), 'TON',   'Metric Ton',    1000,    TRUE),
  (uuid_generate_v4(), 'DOZEN', 'Dozen',           12,    TRUE)
ON CONFLICT (uom_code) DO NOTHING;

-- Seed core permissions
INSERT INTO permissions (id, perm_code, module, action, description) VALUES
  -- Company
  (uuid_generate_v4(),'company.create',  'company',   'create','Create companies'),
  (uuid_generate_v4(),'company.read',    'company',   'read',  'View companies'),
  (uuid_generate_v4(),'company.update',  'company',   'update','Update company details'),
  (uuid_generate_v4(),'company.delete',  'company',   'delete','Deactivate companies'),
  -- Branch
  (uuid_generate_v4(),'branch.create',   'branch',    'create','Create branches'),
  (uuid_generate_v4(),'branch.read',     'branch',    'read',  'View branches'),
  (uuid_generate_v4(),'branch.update',   'branch',    'update','Update branch'),
  (uuid_generate_v4(),'branch.delete',   'branch',    'delete','Deactivate branch'),
  -- User
  (uuid_generate_v4(),'user.create',     'user',      'create','Create users'),
  (uuid_generate_v4(),'user.read',       'user',      'read',  'View users'),
  (uuid_generate_v4(),'user.update',     'user',      'update','Update users'),
  (uuid_generate_v4(),'user.delete',     'user',      'delete','Deactivate users'),
  -- Role
  (uuid_generate_v4(),'role.create',     'role',      'create','Create roles'),
  (uuid_generate_v4(),'role.read',       'role',      'read',  'View roles'),
  (uuid_generate_v4(),'role.update',     'role',      'update','Update roles'),
  (uuid_generate_v4(),'role.delete',     'role',      'delete','Delete roles'),
  -- Customer
  (uuid_generate_v4(),'customer.create', 'customer',  'create','Create customers'),
  (uuid_generate_v4(),'customer.read',   'customer',  'read',  'View customers'),
  (uuid_generate_v4(),'customer.update', 'customer',  'update','Update customers'),
  (uuid_generate_v4(),'customer.delete', 'customer',  'delete','Deactivate customers'),
  -- Vendor
  (uuid_generate_v4(),'vendor.create',   'vendor',    'create','Create vendors'),
  (uuid_generate_v4(),'vendor.read',     'vendor',    'read',  'View vendors'),
  (uuid_generate_v4(),'vendor.update',   'vendor',    'update','Update vendors'),
  (uuid_generate_v4(),'vendor.delete',   'vendor',    'delete','Deactivate vendors'),
  -- Product
  (uuid_generate_v4(),'product.create',  'inventory', 'create','Create products'),
  (uuid_generate_v4(),'product.read',    'inventory', 'read',  'View products'),
  (uuid_generate_v4(),'product.update',  'inventory', 'update','Update products'),
  (uuid_generate_v4(),'product.delete',  'inventory', 'delete','Deactivate products'),
  -- Invoice
  (uuid_generate_v4(),'invoice.create',  'invoice',   'create','Create invoices'),
  (uuid_generate_v4(),'invoice.read',    'invoice',   'read',  'View invoices'),
  (uuid_generate_v4(),'invoice.update',  'invoice',   'update','Update invoices'),
  (uuid_generate_v4(),'invoice.delete',  'invoice',   'delete','Cancel invoices'),
  (uuid_generate_v4(),'invoice.approve', 'invoice',   'approve','Approve invoices'),
  (uuid_generate_v4(),'invoice.print',   'invoice',   'print', 'Print invoices'),
  -- Reports
  (uuid_generate_v4(),'report.read',     'report',    'read',  'View reports'),
  (uuid_generate_v4(),'report.export',   'report',    'export','Export reports')
ON CONFLICT (perm_code) DO NOTHING;
