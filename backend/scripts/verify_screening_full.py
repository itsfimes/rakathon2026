from __future__ import annotations

import hashlib
import json
import resource
import sys

from rakathon_backend.b2.screening.archive import ArchiveScreeningStore
from rakathon_backend.b2.screening.reader import resolve_source, validate_source

DEFAULT_SOURCE = "/mnt/870Ext/sync/programming/rakathon/rakathon2026/vzp_data/Rakathon2026.zip"


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    member = sys.argv[2] if len(sys.argv) > 2 else None
    result = validate_source(explicit=source, member_override=member)
    report = {
        "rows": result.rows,
        "columns": result.columns,
        "distinctPersons": result.distinct_persons,
        "duplicateInvitations": result.duplicate_invitations,
        "emptyNullable": result.empty_nullable,
        "crossMismatches": result.cross_mismatches,
        "firstHash": result.first_hash,
        "midHash": result.mid_hash,
        "endHash": result.end_hash,
        "streamDigest": result.stream_digest,
        "sourceBytes": result.source_bytes,
        "peakRssMb": round(_peak_mb(), 1),
    }
    print(json.dumps(report, indent=2))
    resolved = resolve_source(source if source.strip() else None)
    store = ArchiveScreeningStore(resolved, member)
    samples: list[tuple[str, dict[str, str], int, int]] = [
        ("first100", {}, 100, 0),
        ("mid100", {}, 100, max(0, result.rows // 2)),
        ("end100", {}, 100, max(0, result.rows - 100)),
    ]
    for label, filters, limit, offset in samples:
        page = store.query(dict(filters), ["INVITATION_ID", "PERSON_ID"], limit, offset)
        digest = hashlib.sha256(json.dumps(page.rows, sort_keys=True).encode()).hexdigest()
        print(json.dumps({"sample": label, "count": len(page.rows), "digest": digest}))
    print(json.dumps({"peakRssMb": round(_peak_mb(), 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
