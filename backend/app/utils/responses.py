"""Standard API response builders used by all endpoint modules."""
from __future__ import annotations

from typing import Any

from fastapi.responses import ORJSONResponse


def ok(data: Any = None, message: str = "OK", status_code: int = 200) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=status_code,
        content={"success": True, "message": message, "data": data},
    )


def created(data: Any = None, message: str = "Created") -> ORJSONResponse:
    return ok(data=data, message=message, status_code=201)


def no_content() -> ORJSONResponse:
    return ORJSONResponse(status_code=204, content=None)


def paginated(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    pages: int,
    message: str = "OK",
) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
            },
        },
    )
