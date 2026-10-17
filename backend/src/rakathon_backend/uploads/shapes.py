from __future__ import annotations

from typing import Any


def job_shape(job: dict[str, Any], ai_available: bool = False) -> dict[str, Any]:
    events = job.get("events", [])
    counts: Any = job.get("counts", {})
    mode = str(job.get("modelMode", "azure" if ai_available else "offline"))
    return {
        "version": 1,
        "job": {
            "id": job.get("id"),
            "caseId": job.get("caseId"),
            "filename": job.get("filename"),
            "sha256": job.get("sha256"),
            "sourceUrn": job.get("sourceUrn"),
            "detectedType": job.get("detectedType"),
            "status": job.get("status"),
            "createdAt": job.get("createdAt"),
            "events": events,
            "eventCount": len(events) if isinstance(events, list) else 0,
            "counts": counts if isinstance(counts, dict) else {},
            "recipeReuse": bool(job.get("recipeReuse", False)),
            "newFormat": bool(job.get("newFormat", False)),
            "plannerMode": str(job.get("plannerMode", "none")),
            "model": {
                "providerId": "rakathon-azure",
                "model": "gpt-6-luna-dz-eu",
                "mode": mode,
            },
        },
    }


def binary_envelope(
    status: int, data: bytes, ctype: str, disposition: str
) -> tuple[int, dict[str, str], bytes]:
    headers = {
        "Content-Type": ctype,
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return (status, headers, data)
