"""
app/ai_assistant/knowledge_base.py
──────────────────────────────────────────────────────────────────────────
Static, offline knowledge base for the AI Assistant. No network calls,
no external model — just data describing:

  1. NAV_KB     — where things live in the app (menus/screens/features),
                  used to answer "how do I…" / "where is…" questions and
                  to tell the frontend which page to jump to.

  2. DATA_KB    — the registry of "database question" intents. Each entry
                  maps to a handler function name in `data_queries.py`.
                  Keeping this separate from the handler code means adding
                  a new answerable data question is a two-step, additive
                  change (add an entry here + add a function there).

`page` values match the `id` used by the frontend's `nav('<page>')`
function and the `id="page-<page>"` containers in index.html.
"""
from __future__ import annotations

# ── Navigation / Help knowledge base ────────────────────────────────────────
# Each entry: keywords (substrings matched against the lowercased question),
# the page to deep-link to, and a ready-made offline answer.
NAV_KB: dict[str, dict] = {
    "nav.add_customer": {
        "page": "customers",
        "keywords": [
            "add customer", "new customer", "create customer", "register customer",
            "how do i add a customer", "add a client",
        ],
        "answer": (
            "To add a customer: open **Customers** from the left sidebar, "
            "then click **+ Add Customer**, fill in the name, GSTIN (optional) "
            "and contact details, and click **Save**."
        ),
    },
    "nav.add_vendor": {
        "page": "vendors",
        "keywords": ["add vendor", "new vendor", "create vendor", "add supplier", "new supplier"],
        "answer": (
            "To add a vendor: open **Vendors** from the sidebar, click "
            "**+ Add Vendor**, enter the vendor's details and GSTIN, and **Save**."
        ),
    },
    "nav.add_product": {
        "page": "inventory",
        "keywords": [
            "add product", "new product", "create product", "add item",
            "add stock item", "how do i add a product",
        ],
        "answer": (
            "To add a product: open **Products & Stock**, click **+ Add Product**, "
            "fill in the product name, HSN code, GST rate and pricing, then **Save**."
        ),
    },
    "nav.new_invoice": {
        "page": "create",
        "keywords": [
            "create invoice", "new invoice", "make an invoice", "raise invoice",
            "generate invoice", "how do i create an invoice",
        ],
        "answer": (
            "To create a sales invoice: click **New Invoice** in the sidebar (or the "
            "➕ button in the top bar), pick a customer, add line items, and click **Save**."
        ),
    },
    "nav.gst_settings": {
        "page": "settings",
        "keywords": [
            "gst settings", "gstin setting", "tax settings", "where is gst settings",
            "where is gst setting", "configure gst",
        ],
        "answer": (
            "GST Settings live under **Settings** → the **Company / GST** section, "
            "where you can set your GSTIN, filing frequency and tax preferences."
        ),
    },
    "nav.gst_reports": {
        "page": "gst",
        "keywords": [
            "gst reports", "gstr-1", "gstr1", "gstr-3b", "gstr3b", "hsn summary",
            "where is gst reports", "file gst",
        ],
        "answer": (
            "GST Reports (GSTR-1, GSTR-3B, HSN Summary) are under **GST Reports** "
            "in the sidebar — you can view, export (PDF/JSON/CSV) and file from there."
        ),
    },
    "nav.purchase_orders": {
        "page": "purchase",
        "keywords": [
            "purchase order", "purchase orders", "open purchase orders", "po screen",
            "where is purchase order", "open po",
        ],
        "answer": (
            "Purchase Orders are under **Purchase** in the sidebar — you can create, "
            "track and receive goods against POs there."
        ),
    },
    "nav.quotations": {
        "page": "quotations",
        "keywords": ["quotation", "quotations", "create quote", "new quote", "estimate"],
        "answer": (
            "Quotations are under **Quotations** in the sidebar. You can create a quote "
            "and convert it into an invoice once it's accepted."
        ),
    },
    "nav.returns": {
        "page": "returns",
        "keywords": [
            "credit note", "debit note", "sales return", "purchase return", "returns screen",
        ],
        "answer": (
            "Credit/Debit Notes and returns are under **Returns / Credit** in the sidebar."
        ),
    },
    "nav.einvoice": {
        "page": "einvoice",
        "keywords": ["e-invoice", "einvoice", "irn", "e-way bill", "eway bill", "ewb"],
        "answer": (
            "E-Invoice (IRN) and E-Way Bill generation are under **E-Invoice / E-Way** "
            "in the sidebar."
        ),
    },
    "nav.branches": {
        "page": "branches",
        "keywords": [
            "add branch", "new branch", "create branch", "multi-branch", "manage branches",
            "where is branches", "where are branches", "branches screen", "branches page",
        ],
        "answer": (
            "Branches are managed under **Branches** in the sidebar — add, edit, or view "
            "each branch's manager, monthly target and stock from there."
        ),
    },
    "nav.crm": {
        "page": "crm",
        "keywords": ["crm", "lead", "leads", "add lead", "sales pipeline"],
        "answer": "Leads and the sales pipeline are under **CRM** in the sidebar.",
    },
    "nav.accounting": {
        "page": "accounting",
        "keywords": [
            "accounting", "journal", "balance sheet", "profit and loss", "p&l",
            "where is ledger", "ledger screen", "ledger book",
            "cash book", "bank book", "financial statements",
        ],
        "answer": (
            "Ledgers, journal vouchers and financial statements are under "
            "**Ledger & Books** in the sidebar."
        ),
    },
    "nav.payments": {
        "page": "payments",
        "keywords": ["record payment", "add payment", "payments screen", "receive payment"],
        "answer": (
            "To record a payment, open **Payments** in the sidebar, or use the "
            "**Record Payment** button on an invoice or purchase order."
        ),
    },
    "nav.reports": {
        "page": "reports",
        "keywords": ["reports screen", "sales report", "where are reports", "business reports"],
        "answer": "General business reports are under **Reports** in the sidebar.",
    },
    "nav.audit_log": {
        "page": "auditlog",
        "keywords": ["audit log", "activity log", "who changed", "user activity"],
        "answer": "The Audit Log (all user actions with timestamps) is under **Audit Log** in the sidebar.",
    },
    "nav.settings": {
        "page": "settings",
        "keywords": ["settings screen", "app settings", "company profile", "where are settings"],
        "answer": "App and company settings are under **Settings** in the sidebar.",
    },
    "nav.dashboard": {
        "page": "dashboard",
        "keywords": ["dashboard", "home screen", "overview screen"],
        "answer": "The **Dashboard** (sidebar top) gives you an overview of sales, stock and dues.",
    },
}

# ── Database-question knowledge base ────────────────────────────────────────
# `handler` must match a function name exported from `data_queries.py`.
DATA_KB: dict[str, dict] = {
    "data.today_sales": {
        "handler": "today_sales",
        "keywords": [
            "today's sales", "todays sales", "sales today", "how much did i sell today",
            "today's revenue", "revenue today",
        ],
    },
    "data.month_sales": {
        "handler": "month_sales",
        "keywords": [
            "this month's sales", "month sales", "sales this month", "monthly sales",
            "revenue this month",
        ],
    },
    "data.low_stock": {
        "handler": "low_stock",
        "keywords": [
            "low stock", "stock low", "which products are low", "reorder", "running out of stock",
            "out of stock",
        ],
    },
    "data.top_customers": {
        "handler": "top_customers",
        "keywords": ["top customers", "best customers", "biggest customers"],
    },
    "data.pending_payments": {
        "handler": "pending_payments",
        "keywords": [
            "pending payments", "outstanding payments", "dues", "amount due", "overdue invoices",
            "unpaid invoices", "total receivables", "sundry debtors", "amount receivable",
        ],
    },
    "data.open_purchase_orders": {
        "handler": "open_purchase_orders",
        "keywords": [
            "how many purchase orders", "how many open purchase orders",
            "count of purchase orders", "purchase orders pending count",
        ],
    },
    "data.customer_count": {
        "handler": "customer_count",
        "keywords": ["how many customers", "total customers", "number of customers"],
    },
    "data.branch_list": {
        "handler": "branch_list",
        "keywords": [
            "list branches", "show branches", "show all branches", "all branches",
            "how many branches", "branch list", "list of branches", "view branches",
        ],
    },
    "data.branch_performance": {
        "handler": "branch_performance",
        "keywords": [
            "branch performance", "branch wise sales", "branch-wise sales", "sales by branch",
            "which branch is best", "which branch is performing", "best performing branch",
            "top branch", "compare branches", "branch comparison", "branch sales",
        ],
    },
    "data.total_payables": {
        "handler": "total_payables",
        "keywords": [
            "total payables", "total payable", "sundry creditors", "amount payable to vendors",
            "vendor dues", "how much do i owe vendors", "creditors", "payables",
        ],
    },
    "data.cash_balance": {
        "handler": "cash_balance",
        "keywords": ["cash balance", "cash in hand", "how much cash do i have", "cash on hand"],
    },
    "data.bank_balance": {
        "handler": "bank_balance",
        "keywords": [
            "bank balance", "bank balances", "how much money in bank", "money in the bank",
        ],
    },
    "data.accounts_summary": {
        "handler": "accounts_summary",
        "keywords": [
            "chart of accounts", "how many accounts", "list of accounts", "accounts summary",
            "account groups",
        ],
    },
}
