# VyaparPro ERP — Production-Ready GST Billing & ERP System

> Better than BillSoft. Built for Indian SMBs.

## 🚀 Features
- **GST Billing**: Tax Invoices, Credit Notes, Debit Notes, E-Invoice ready
- **Job Orders & PO Tracking**: Full JO ↔ PO ↔ Invoice lifecycle
- **Quotation Management**: Quote → Sales Order → Invoice conversion
- **Purchase Orders**: PO → GRN → Purchase Bill
- **Delivery Challans** with E-Way Bill support
- **Inventory Management**: Multi-warehouse, Batch, Serial, Expiry tracking
- **Accounting**: Double-entry, Trial Balance, P&L, Balance Sheet
- **GST Returns**: GSTR-1, GSTR-3B auto-computation
- **Multi-Company & Multi-Branch**
- **Role-Based Access Control** with granular permissions
- **JWT Authentication + 2FA (TOTP)**
- **Redis Caching** for high performance
- **PDF Generation** (ReportLab)
- **QR Code & Barcode** support
- **Audit Logging** (tamper-proof)
- **WhatsApp & Email** sharing

## 📁 Project Structure
```
vyaparpro/
├── backend/                  # FastAPI Python Backend
│   ├── app/
│   │   ├── api/v1/endpoints/ # All REST API routes
│   │   ├── core/             # Config, Security, Exceptions, Logging
│   │   ├── db/
│   │   │   ├── models/       # SQLAlchemy ORM models
│   │   │   └── repositories/ # Data access layer
│   │   ├── middleware/       # Request ID, Timing, Audit
│   │   ├── schemas/          # Pydantic v2 request/response schemas
│   │   ├── services/         # Business logic layer
│   │   └── utils/            # GST calc, PDF, QR, Validators
│   ├── alembic/              # Database migrations
│   ├── scripts/init.sql      # PostgreSQL bootstrap + seed data
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── pyproject.toml
└── frontend_html/
    └── index.html            # Complete VyaparPro Web UI (standalone HTML)
```

## ⚡ Quick Start (Docker — Recommended)

```bash
cd backend

# 1. Copy environment file
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY, POSTGRES_PASSWORD etc.

# 2. Start all services
docker compose up -d

# 3. Run database migrations
docker compose exec api alembic upgrade head

# 4. Open API docs
open http://localhost:8000/docs

# 5. Open the Web UI
open ../frontend_html/index.html
```

## 🛠️ Local Development

```bash
cd backend

# Install dependencies
pip install poetry
poetry install

# Start PostgreSQL & Redis (via Docker or local install)
docker compose up db redis -d

# Copy and edit .env
cp .env.example .env

# Run migrations
alembic upgrade head

# Start dev server with hot reload
uvicorn app.main:app --reload --port 8000
```

## 🗄️ Database Setup

PostgreSQL 16 with these extensions:
- `uuid-ossp` — UUID generation
- `pg_trgm` — Fast text search
- `btree_gin` — Composite indexes

The `scripts/init.sql` seeds:
- GST Rate slabs (0%, 5%, 12%, 18%, 28%)
- 17 standard Units of Measure
- All 36 permission codes

## 📡 API Overview

| Module | Base Path |
|--------|-----------|
| Auth | `/api/v1/auth` |
| Users | `/api/v1/users` |
| Roles | `/api/v1/roles` |
| Permissions | `/api/v1/permissions` |
| Sessions | `/api/v1/sessions` |
| Companies | `/api/v1/companies` |
| Branches | `/api/v1/companies/{id}/branches` |
| Customers | `/api/v1/customers` |
| Vendors | `/api/v1/vendors` |
| Products | `/api/v1/products` |
| Master Data | `/api/v1/master` (categories, UOMs, GST rates, HSN) |
| Quotations | `/api/v1/billing/quotations` |
| Job Orders | `/api/v1/billing/job-orders` |
| Purchase Orders | `/api/v1/billing/purchase-orders` |
| Invoices | `/api/v1/billing/invoices` |
| Payments | `/api/v1/billing/payments` |
| Delivery Challans | `/api/v1/billing/delivery-challans` |

## 🔐 Default Roles (seeded)
- **Super Admin** — Full access
- **Accountant** — Billing + Accounting
- **Sales** — Quotations + Invoices + Customers
- **Store Manager** — Inventory + Purchase Orders
- **Viewer** — Read-only

## 🐳 Docker Services

| Service | Port | Description |
|---------|------|-------------|
| FastAPI | 8000 | Main API server |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | Cache + Sessions |
| pgAdmin | 5050 | DB admin UI |
| Celery Worker | — | Background tasks |
| Flower | 5555 | Task monitor |

## 🧾 GST Features
- Automatic CGST/SGST split for intra-state
- IGST for inter-state
- Zero-rated exports
- Reverse charge mechanism
- HSN/SAC code lookup
- E-Invoice JSON preparation (IRN ready)
- E-Way Bill field support
- GSTR-1 data extraction
- GSTR-3B auto-computation
- ITC Ledger tracking

## 📊 Reports Available
- Trial Balance
- Profit & Loss Statement
- Balance Sheet
- Cash Book / Bank Book
- Account Ledger
- GST Summary (monthly/quarterly)
- GSTR-1 register
- GSTR-3B computation
- Outstanding Receivables / Payables
- Stock Valuation
- Low Stock Alerts
- Inventory Movement Report

## 🔑 Environment Variables (key ones)

```env
APP_ENV=production
JWT_SECRET_KEY=<64-char random string>
POSTGRES_PASSWORD=<strong password>
REDIS_PASSWORD=<redis password>
SMTP_USER=<your email>
SMTP_PASSWORD=<app password>
SENTRY_DSN=<optional>
```

## 📦 Tech Stack
- **Backend**: FastAPI 0.111, Python 3.11, SQLAlchemy 2.0 (async)
- **Database**: PostgreSQL 16
- **Cache**: Redis 7
- **Auth**: JWT (python-jose) + bcrypt + TOTP (pyotp)
- **PDF**: ReportLab
- **Migrations**: Alembic
- **Tasks**: Celery + Flower
- **Container**: Docker + Docker Compose

---
Built with ❤️ for Indian SMBs | VyaparPro ERP v2.0
