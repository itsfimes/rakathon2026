from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from rakathon_backend.b2.iris.config import TRUSTED_REMOTE_BASE
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.env_file import apply_env_file
from rakathon_backend.runtime.iris_fhir import IRIS_FHIR_MODE, fhir_only_store_from_env
from rakathon_backend.runtime.secret_config import remove_client_config, write_client_config

CALL_TIMEOUT = 30.0
PROBE_BUDGET = 180.0
PROBE_PREFIX = "rakathon-probe-"
IDENTITY_SYSTEM = "urn:rakathon:verification"
PROBE_TAG = "SYNTHETIC-LIVE-PROBE"
REV1 = "Synthetic Probe Rev1"
REV2 = "Synthetic Probe Rev2"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="verify_iris_live")
    parser.add_argument("--env-file", default="iris.env")
    parser.add_argument("--runtime-base", default="/tmp/opencode")
    parser.add_argument("--write-probe", action="store_true")
    return parser.parse_args(argv)


def probe_fixture(pid: str, name: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": pid,
        "active": False,
        "name": [{"text": name}],
        "identifier": [{"system": IDENTITY_SYSTEM, "value": pid}],
        "meta": {"tag": [{"code": PROBE_TAG}]},
    }


def fixture_matches(resource: dict[str, Any], pid: str, name: str) -> bool:
    if resource.get("id") != pid or resource.get("active") is not False:
        return False
    if resource.get("name") != [{"text": name}]:
        return False
    identifiers = resource.get("identifier", [])
    if (
        not isinstance(identifiers, list)
        or {"system": IDENTITY_SYSTEM, "value": pid} not in identifiers
    ):
        return False
    meta = resource.get("meta", {})
    tags = meta.get("tag", []) if isinstance(meta, dict) else []
    return isinstance(tags, list) and {"code": PROBE_TAG} in tags


def direct_client(user: str, password: str) -> httpx.Client:
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    return httpx.Client(
        base_url=TRUSTED_REMOTE_BASE,
        auth=(user, password),
        verify=True,
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        headers={"Accept": "application/fhir+json"},
    )


def owned_check(resource: dict[str, Any], pid: str) -> bool:
    if resource.get("id") != pid:
        return False
    identifiers = resource.get("identifier", [])
    if not isinstance(identifiers, list):
        return False
    return {"system": IDENTITY_SYSTEM, "value": pid} in identifiers


async def main_async(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    partial: dict[str, Any] = {}
    try:
        filled = apply_env_file(args.env_file)
    except (OSError, PermissionError, ValueError) as exc:
        print(json.dumps({"error": "env_file_rejected", "message": str(exc)}))
        return 2
    user = os.environ.get("RAKATHON_IRIS_FHIR_USER", "")
    password = os.environ.get("RAKATHON_IRIS_FHIR_PASSWORD", "")
    try:
        store = fhir_only_store_from_env()
    except (AuthError, ContractError, TransportError, OSError, ValueError) as exc:
        print(json.dumps({"error": "iris_not_configured", "message": str(exc)}))
        return 2
    base = Path(args.runtime_base)
    base.mkdir(parents=True, exist_ok=True)
    runtime_dir = Path(tempfile.mkdtemp(prefix="rakathon-live-", dir=str(base)))
    app = BackendApp(runtime_dir, fresh_tokens(), store=store, mode=IRIS_FHIR_MODE)
    await app.start()
    owned_id: str | None = None
    try:
        if time.monotonic() - t0 > PROBE_BUDGET:
            print(json.dumps({"error": "probe_budget_exceeded"}))
            return 1
        config_path = write_client_config(runtime_dir, app.tokens, "mock", IRIS_FHIR_MODE)
        client_mode = json.loads(config_path.read_text(encoding="utf-8")).get("mode", "")

        async def b4(
            action: str, payload: dict[str, Any], user_id: str = "admin"
        ) -> dict[str, Any]:
            if time.monotonic() - t0 > PROBE_BUDGET - CALL_TIMEOUT:
                raise TimeoutError("probe budget exhausted")
            request = new_envelope(
                source=f"frontend:{user_id}",
                target="b4",
                action=action,
                data_kind=request_kind(action),
                payload=dict(payload),
                user_id=user_id,
            )
            client = app.frontend_client(user_id)
            reply = await asyncio.wait_for(
                client.call(request, expect_source="b4"), timeout=CALL_TIMEOUT
            )
            return dict(reply.payload)

        with direct_client(user, password) as http:
            meta_response = http.get("/metadata")
            meta_version = ""
            if meta_response.status_code == 200:
                try:
                    meta_body = meta_response.json()
                except ValueError:
                    meta_body = {}
                if isinstance(meta_body, dict):
                    meta_version = str(meta_body.get("fhirVersion", ""))
        summary = await b4("fhir.search", {"resourceType": "Patient", "_summary": "count"}, "admin")
        bundle = summary.get("bundle", {})
        server_total = summary.get("serverTotal")
        count_total = bundle.get("total") if isinstance(bundle, dict) else None
        result: dict[str, Any] = {
            "mode": IRIS_FHIR_MODE,
            "clientMode": client_mode,
            "appMode": app.mode,
            "metadataStatus": meta_response.status_code,
            "fhirVersion": meta_version,
            "countTotal": count_total,
            "serverTotal": server_total,
            "entryCount": len(bundle.get("entry", [])) if isinstance(bundle, dict) else -1,
            "envKeys": sorted(filled),
        }
        if not isinstance(server_total, int) or server_total <= 0:
            print(json.dumps({**result, "error": "count_not_positive"}))
            return 1
        if count_total != server_total:
            print(json.dumps({**result, "error": "count_total_mismatch"}))
            return 1
        if not args.write_probe:
            print(json.dumps({**result, "lifecycle": "read_only"}))
            return 0
        _ = user
        pid = PROBE_PREFIX + uuid.uuid4().hex
        assert len(pid) <= 64
        result["probeId"] = pid
        pre = await b4("fhir.read", {"resourceType": "Patient", "id": pid})
        pre_bundle = pre.get("bundle", {})
        if not isinstance(pre_bundle, dict) or pre_bundle.get("total", 1) != 0:
            print(json.dumps({**result, "error": "collision_abort", "probeId": pid}))
            return 1
        owned_id = pid
        partial = {"probeId": pid}
        try:
            if time.monotonic() - t0 > PROBE_BUDGET - 60.0:
                raise TimeoutError("probe budget low before create")
            created = await b4("fhir.write", probe_fixture(pid, REV1))
            if created.get("stored") != [f"Patient/{pid}"]:
                raise ValueError("create stored mismatch")
            got = await b4("fhir.read", {"resourceType": "Patient", "id": pid})
            entries = got.get("bundle", {}).get("entry", [])
            if len(entries) != 1 or not fixture_matches(entries[0].get("resource", {}), pid, REV1):
                raise ValueError("create readback mismatch")
            revised = await b4("fhir.write", probe_fixture(pid, REV2))
            if revised.get("stored") != [f"Patient/{pid}"]:
                raise ValueError("update stored mismatch")
            got2 = await b4("fhir.read", {"resourceType": "Patient", "id": pid})
            entries2 = got2.get("bundle", {}).get("entry", [])
            if len(entries2) != 1 or not fixture_matches(
                entries2[0].get("resource", {}), pid, REV2
            ):
                raise ValueError("update readback mismatch")
            result["lifecycle"] = "created_updated"
            result["probeId"] = pid
        finally:
            if owned_id is not None:
                cleanup = cleanup_probe(user, password, owned_id, REV2)
                result["cleanup"] = cleanup
                partial = {"probeId": pid, "cleanup": cleanup.get("status")}
                owned_id = None
                try:
                    post = await b4("fhir.read", {"resourceType": "Patient", "id": pid})
                except (
                    AuthError,
                    ContractError,
                    TransportError,
                    OSError,
                    TimeoutError,
                ) as post_exc:
                    result["postDeleteBackend"] = getattr(post_exc, "code", type(post_exc).__name__)
                else:
                    post_bundle = post.get("bundle", {})
                    result["postDeleteTotal"] = (
                        post_bundle.get("total") if isinstance(post_bundle, dict) else None
                    )
        if result.get("cleanup", {}).get("status") not in ("deleted_200", "deleted_204"):
            print(json.dumps(result))
            return 1
        if result.get("postDeleteTotal") == 0:
            print(json.dumps(result))
            return 0
        if "postDeleteBackend" in result and result.get("cleanup", {}).get("confirm") in (
            404,
            410,
        ):
            print(json.dumps({**result, "postDeleteNote": "backend_tombstone_direct_gone"}))
            return 0
        print(json.dumps({**result, "error": "post_delete_visible"}))
        return 1
    except (AuthError, ContractError, TransportError, OSError, TimeoutError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc), **partial}))
        return 1
    finally:
        await app.close()
        store.close()
        remove_client_config(runtime_dir)


def cleanup_probe(user: str, password: str, pid: str, name: str) -> dict[str, Any]:
    try:
        with direct_client(user, password) as http:
            fetched = http.get(f"/Patient/{pid}")
            if fetched.status_code == 404:
                return {"transport": "direct", "status": "already_absent"}
            if fetched.status_code != 200:
                return {"transport": "direct", "status": f"fetch_{fetched.status_code}"}
            try:
                body = fetched.json()
            except ValueError:
                return {"transport": "direct", "status": "fetch_invalid"}
            if not isinstance(body, dict) or not owned_check(body, pid):
                return {"transport": "direct", "status": "refused_unowned"}
            if not fixture_matches(body, pid, name):
                return {"transport": "direct", "status": "refused_fixture_mismatch"}
            deleted = http.request("DELETE", f"/Patient/{pid}")
            if deleted.status_code not in (200, 204):
                return {"transport": "direct", "status": f"delete_{deleted.status_code}"}
            confirm = http.get(f"/Patient/{pid}")
            return {
                "transport": "direct",
                "status": f"deleted_{deleted.status_code}",
                "confirm": confirm.status_code,
            }
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return {"transport": "direct", "status": f"error_{type(exc).__name__}"}


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
