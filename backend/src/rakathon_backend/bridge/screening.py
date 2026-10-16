from __future__ import annotations

from typing import Any

from rakathon_backend.common.errors import ContractError

SCREENING_OPERATIONS = frozenset({"screening.import", "screening.query"})


def dispatch_screening(target: Any, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "screening.import":
        if target is None or getattr(target, "import_batch", None) is None:
            raise ContractError(code="not_configured", message="screening store unavailable")
        return dict(target.import_batch(list(args["rows"])))
    if target is None or getattr(target, "query", None) is None:
        raise ContractError(code="not_configured", message="screening store unavailable")
    items = target.query(
        dict(args["filters"]),
        list(args["projection"]),
        int(args["limit"]),
        int(args["offset"]),
    )
    if isinstance(items, list):
        return {"rows": [dict(x) for x in items if isinstance(x, dict)]}
    return {"rows": [dict(x) for x in items.rows]}
