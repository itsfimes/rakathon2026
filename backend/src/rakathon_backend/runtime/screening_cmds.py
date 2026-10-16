from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b2.iris.screening_sql import MAX_BATCH, ScreeningSqlStore
from rakathon_backend.b2.screening import archive, schema
from rakathon_backend.b2.screening.archive import ArchiveScreeningStore
from rakathon_backend.b2.screening.reader import (
    ResolvedSource,
    iter_validated_rows,
    resolve_source,
    validate_source,
)
from rakathon_backend.bridge.client import EncryptedBridgeStorage
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import make_client, new_envelope
from rakathon_backend.runtime import bridge_cmds as _bridge_cmds


def archive_store_from_env(explicit: str | None) -> Any | None:
    raw = (explicit or "").strip()
    if not raw:
        raw = os.environ.get("RAKATHON_SCREENING_SOURCE", "").strip()
    if not raw:
        return None
    try:
        resolved = resolve_source(raw)
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        raise
    return ArchiveScreeningStore(resolved)


def cmd_screening_validate(args: argparse.Namespace) -> int:
    try:
        result = validate_source(
            explicit=str(getattr(args, "source", "") or ""),
            member_override=(str(getattr(args, "member", "") or "") or None),
        )
    except (ContractError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
        print(json.dumps({"error": code, "message": str(exc)}))
        return 2
    print(
        json.dumps(
            {
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
            },
            indent=2,
        )
    )
    return 0


async def cmd_screening_query(args: argparse.Namespace) -> int:
    runtime_dir = Path(str(args.runtime_dir))
    config_path = runtime_dir / "demo-client.json"
    if not config_path.exists():
        print(json.dumps({"error": "missing demo-client.json"}))
        return 2
    body = json.loads(config_path.read_text(encoding="utf-8"))
    tokens = body.get("tokens", {})
    user = str(args.user)
    source = f"frontend:{user}"
    token = tokens.get(source, "")
    if not token:
        print(json.dumps({"error": "unknown user"}))
        return 2
    try:
        raw_filters = json.loads(str(getattr(args, "filters_json", "") or "{}"))
        raw_projection: list[str] | None = None
        if getattr(args, "projection", "") or "":
            raw_projection = [p.strip() for p in str(args.projection).split(",") if p.strip()]
        filters, projection, limit, offset = archive.check_query_args(
            raw_filters, raw_projection, int(args.limit), int(args.offset)
        )
    except (ContractError, ValueError) as exc:
        code = exc.code if isinstance(exc, ContractError) else "bad_payload"
        print(json.dumps({"error": code, "message": str(exc)}))
        return 2
    client = make_client(runtime_dir, target="b4", source=source, token=str(token), timeout=30.0)
    request = new_envelope(
        source=source,
        target="b4",
        action="screening.query",
        data_kind=request_kind("screening.query"),
        payload={
            "filters": filters,
            "projection": projection,
            "limit": limit,
            "offset": offset,
        },
        user_id=user,
    )
    try:
        reply = await client.call(request, expect_source="b4")
    except (AuthError, ContractError, TransportError, OSError, TimeoutError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1
    rows = reply.payload.get("rows", [])
    count = reply.payload.get("count", 0)
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    summary: dict[str, Any] = {
        "count": count,
        "truncated": reply.payload.get("truncated", False),
        "rowsDigest": digest,
        "mode": reply.payload.get("mode", "mock"),
    }
    if bool(getattr(args, "include_rows", False)):
        summary["rows"] = rows
    print(json.dumps(summary, indent=2))
    return 0


def cmd_screening_import(args: argparse.Namespace) -> int:
    try:
        batch_size = int(getattr(args, "batch_size", 500))
    except ValueError:
        print(json.dumps({"error": "batch_size invalid"}))
        return 2
    if batch_size < 1 or batch_size > MAX_BATCH:
        print(json.dumps({"error": "batch_size must be 1..500"}))
        return 2
    try:
        resolved: ResolvedSource = resolve_source(str(getattr(args, "source", "") or ""))
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2
    try:
        bridge = _bridge_cmds.bridge_store_from_env()
    except (ContractError, TransportError, OSError, ValueError) as exc:
        print(json.dumps({"error": "bridge_not_configured", "message": str(exc)}))
        return 2
    assert isinstance(bridge, EncryptedBridgeStorage)
    imported = 0
    skipped = 0
    batches = 0
    try:
        batch: list[dict[str, str]] = []
        member = str(getattr(args, "member", "") or "") or None
        for _lineno, record in iter_validated_rows(resolved, member):
            batch.append(record)
            if len(batch) >= batch_size:
                counts = bridge.screening_import(batch)
                imported += int(counts["imported"])
                skipped += int(counts["skipped"])
                batches += 1
                batch = []
        if batch:
            counts = bridge.screening_import(batch)
            imported += int(counts["imported"])
            skipped += int(counts["skipped"])
            batches += 1
    except (ContractError, TransportError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
        print(json.dumps({"error": code, "message": str(exc)}))
        return 1
    finally:
        bridge.close()
    print(json.dumps({"imported": imported, "skipped": skipped, "batches": batches}))
    return 0


def cmd_screening_init_db() -> int:
    try:
        sql_config = IrisSqlConfig.from_env(dict(os.environ))
    except ContractError as exc:
        print(json.dumps({"error": "iris sql is not configured", "message": exc.message}))
        return 2
    store = ScreeningSqlStore(sql_config)
    try:
        result = store.init_db()
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    print(json.dumps(result))
    return 0


def screening_columns() -> list[str]:
    return list(schema.HEADER)
