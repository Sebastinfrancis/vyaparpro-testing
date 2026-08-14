"""
Cross-dialect column types.

VyaparPro runs on PostgreSQL server-side and on SQLite in the packaged
desktop edition. These TypeDecorators use native PostgreSQL types when
connected to Postgres, and fall back to SQLite-compatible equivalents
otherwise, so model files never need to branch on dialect themselves.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import INET as PG_INET
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class UUID(TypeDecorator):
    """Postgres native UUID on Postgres; 36-char string elsewhere.
    Always returns uuid.UUID objects to Python code."""
    impl = CHAR
    cache_ok = True

    def __init__(self, as_uuid: bool = True, *args: Any, **kwargs: Any) -> None:
        self.as_uuid = as_uuid
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=self.as_uuid))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None or not self.as_uuid:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONB(TypeDecorator):
    """JSONB on Postgres; plain JSON everywhere else."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())


class ARRAY(TypeDecorator):
    """Postgres ARRAY on Postgres; JSON-encoded list elsewhere."""
    impl = JSON
    cache_ok = True

    def __init__(self, item_type: Any = Text, *args: Any, **kwargs: Any) -> None:
        self.item_type = item_type
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(self.item_type))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return list(value) if value is not None else value

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return list(value) if value is not None else value


class INET(TypeDecorator):
    """Postgres INET on Postgres; plain text elsewhere."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_INET())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else value

    def process_result_value(self, value, dialect):
        return str(value) if value is not None else value