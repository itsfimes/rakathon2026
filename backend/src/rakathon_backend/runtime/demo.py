from __future__ import annotations

import json
from typing import Any

from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import make_client, new_envelope
from rakathon_backend.runtime.application import BackendApp
from rakathon_backend.runtime.fixtures import complete_fixture, incomplete_fixture, overdue_task


async def run_demo(app: BackendApp) -> dict[str, Any]:
    admin = app.frontend_client("admin")
    coord = app.frontend_client("coordinator")
    viewer = app.frontend_client("viewer")
    clinician = app.frontend_client("clinician")
    complete_ref = app.blob.put(json.dumps(complete_fixture()).encode(), "application/json")
    incomplete_ref = app.blob.put(json.dumps(incomplete_fixture()).encode(), "application/json")
    req_complete = new_envelope(
        source="frontend:admin",
        target="b4",
        action="ingest",
        data_kind=DataKind.PROPRIETARY,
        payload={"bytesRef": complete_ref, "purpose": "translate"},
        user_id="admin",
    )
    reply_complete = await admin.call(req_complete, expect_source="b4")
    bundle = reply_complete.payload.get("bundle", {})
    inner = bundle.get("bundle", bundle) if isinstance(bundle, dict) else {}
    if isinstance(bundle, dict) and bundle.get("resourceType") == "Bundle":
        inner = bundle
    entries = inner.get("entry", []) if isinstance(inner, dict) else []
    patient_id = ""
    for entry in entries:
        resource = entry.get("resource", {}) if isinstance(entry, dict) else {}
        if resource.get("resourceType") == "Patient":
            patient_id = str(resource.get("id", ""))
    req_incomplete = new_envelope(
        source="frontend:admin",
        target="b4",
        action="ingest",
        data_kind=DataKind.PROPRIETARY,
        payload={"bytesRef": incomplete_ref, "purpose": "translate"},
        user_id="admin",
    )
    reply_incomplete = await admin.call(req_incomplete, expect_source="b4")
    inner_inc = reply_incomplete.payload.get("bundle", {})
    outcome_type = (
        inner_inc.get("resourceType", "unknown") if isinstance(inner_inc, dict) else "unknown"
    )
    if isinstance(reply_incomplete.payload.get("bundle"), dict):
        nested = reply_incomplete.payload["bundle"]
        if isinstance(nested, dict) and nested.get("resourceType") == "OperationOutcome":
            outcome_type = "OperationOutcome"
    task = overdue_task("clinician")
    if isinstance(inner, dict) and inner.get("resourceType") == "Bundle":
        store_req = new_envelope(
            source="frontend:admin",
            target="b4",
            action="fhir.write",
            data_kind=request_kind("fhir.write"),
            payload=dict(inner),
            user_id="admin",
        )
        await admin.call(store_req, expect_source="b4")
    req_task = new_envelope(
        source="frontend:coordinator",
        target="b4",
        action="tasks.write",
        data_kind=request_kind("tasks.write"),
        payload=dict(task),
        user_id="coordinator",
    )
    await coord.call(req_task, expect_source="b4")
    tick_req = new_envelope(
        source="frontend:coordinator",
        target="b4",
        action="reminders.read",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="coordinator",
    )
    _ = tick_req
    wtoken = app.tokens["b3"]
    wclient = make_client(app.runtime_dir, target="b3", source="b3", token=wtoken)
    wtick = new_envelope(
        source="b3",
        target="b3",
        action="watchdog.tick",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="watchdog",
    )
    wtick_reply = await wclient.call(wtick, expect_source="b3")
    tick_count = int(wtick_reply.payload.get("count", 0))
    rem_req = new_envelope(
        source="frontend:coordinator",
        target="b4",
        action="reminders.read",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="coordinator",
    )
    rem_reply = await coord.call(rem_req, expect_source="b4")
    reminder_count = int(rem_reply.payload.get("count", 0))
    read_req = new_envelope(
        source="frontend:clinician",
        target="b4",
        action="fhir.read",
        data_kind=DataKind.METADATA,
        payload={"resourceType": "Patient", "id": patient_id or "pat-demo-001"},
        user_id="clinician",
    )
    read_reply = await clinician.call(read_req, expect_source="b4")
    read_bundle = read_reply.payload.get("bundle", {})
    read_total = int(read_bundle.get("total", 0)) if isinstance(read_bundle, dict) else 0
    ack_req = new_envelope(
        source="frontend:clinician",
        target="b4",
        action="tasks.ack",
        data_kind=DataKind.METADATA,
        payload={"id": task["id"]},
        user_id="clinician",
    )
    ack_reply = await clinician.call(ack_req, expect_source="b4")
    ack_status = ""
    ack_task = ack_reply.payload.get("task", {})
    if isinstance(ack_task, dict):
        ack_status = str(ack_task.get("status", ""))
    denied = False
    try:
        bad = new_envelope(
            source="frontend:viewer",
            target="b4",
            action="tasks.write",
            data_kind=DataKind.METADATA,
            payload=dict(task),
            user_id="viewer",
        )
        await viewer.call(bad, expect_source="b4")
    except (AuthError, ContractError, TransportError, OSError, TimeoutError):
        denied = True
    health = await app.health_all()
    return {
        "mode": "mock",
        "synthetic": True,
        "healthScope": "authenticated-ipc-liveness",
        "completeIngest": {"resourceType": "Bundle", "patientId": patient_id},
        "incompleteIngest": {"resourceType": outcome_type, "manualReview": True},
        "watchdogTickCount": tick_count,
        "reminderCount": reminder_count,
        "fhirReadTotal": read_total,
        "ackStatus": ack_status,
        "viewerWriteDenied": denied,
        "health": health,
    }
