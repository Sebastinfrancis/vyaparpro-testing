"""Pagination helpers — build consistent paginated API responses."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from app.db.repositories.base import Pagination

T = TypeVar("T")


def paginated_response(
    pagination: Pagination,
    serializer: Callable[[Any], dict] | None = None,
) -> dict:
    """
    Convert a Pagination object into the standard API envelope.

    Args:
        pagination: result from BaseRepository.paginate()
        serializer: optional callable to transform each item (e.g. schema.model_validate)
    """
    items = (
        [serializer(item) for item in pagination.items]
        if serializer
        else pagination.items
    )
    return {
        "success": True,
        "data": {
            "items": items,
            "total": pagination.total,
            "page": pagination.page,
            "page_size": pagination.page_size,
            "pages": pagination.pages,
        },
    }
