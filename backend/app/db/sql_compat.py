"""
SQL fragments that differ between PostgreSQL and SQLite, for use inside raw
text() queries in reporting/dashboard endpoints. The DB backend
(settings.DB_ENGINE) is fixed for the lifetime of a deployment, so these are
plain functions rather than something resolved per-query.
"""
from app.core.config import settings


def month_start_sql() -> str:
    """SQL expression for the first day of the current month, as a date."""
    if settings.DB_ENGINE == "sqlite":
        return "date('now', 'start of month')"
    return "date_trunc('month', CURRENT_DATE)"


def days_since_sql(column: str) -> str:
    """SQL expression for whole days elapsed since `column` (a date/timestamp)."""
    if settings.DB_ENGINE == "sqlite":
        return f"CAST(julianday('now') - julianday({column}) AS INTEGER)"
    return f"(CURRENT_DATE - {column}::date)"