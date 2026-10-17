from __future__ import annotations

import importlib
import json
import re
from typing import Any

from pydantic import ValidationError

from rakathon_backend.common.errors import ContractError

MODELS = {
    name: getattr(importlib.import_module(f"fhir.resources.{module}"), name)
    for name, module in {
        "Patient": "patient",
        "Condition": "condition",
        "Observation": "observation",
        "DiagnosticReport": "diagnosticreport",
        "DocumentReference": "documentreference",
        "ServiceRequest": "servicerequest",
        "Procedure": "procedure",
        "Provenance": "provenance",
        "OperationOutcome": "operationoutcome",
        "Bundle": "bundle",
        "Task": "task",
    }.items()
}
ENUMS: dict[str, dict[str, set[str]]] = {
    "Patient": {"gender": {"male", "female", "other", "unknown"}},
    "ServiceRequest": {
        "intent": {
            "proposal",
            "plan",
            "directive",
            "order",
            "original-order",
            "reflex-order",
            "filler-order",
            "instance-order",
            "option",
        },
        "priority": {"routine", "urgent", "asap", "stat"},
    },
    "DocumentReference": {"docStatus": {"preliminary", "final", "amended", "entered-in-error"}},
}
CONDITION_STATUS = {
    "clinicalStatus": (
        "http://terminology.hl7.org/CodeSystem/condition-clinical",
        {"active", "recurrence", "relapse", "inactive", "remission", "resolved"},
    ),
    "verificationStatus": (
        "http://terminology.hl7.org/CodeSystem/condition-ver-status",
        {"unconfirmed", "provisional", "differential", "confirmed", "refuted", "entered-in-error"},
    ),
}


def _fail() -> ContractError:
    return ContractError(code="bad_payload", message="Resource is not valid supported FHIR R4")


def _same(raw: Any, parsed: Any) -> None:
    if isinstance(raw, dict):
        if not isinstance(parsed, dict):
            raise _fail()
        for key, value in raw.items():
            if key not in parsed:
                raise _fail()
            _same(value, parsed[key])
    elif isinstance(raw, list):
        if not isinstance(parsed, list) or len(raw) != len(parsed):
            raise _fail()
        for left, right in zip(raw, parsed, strict=True):
            _same(left, right)
    elif type(raw) in (bool, str, int, float):
        if type(raw) is not type(parsed) or (not isinstance(raw, str) and raw != parsed):
            raise _fail()
    else:
        raise _fail()


def _raw_types(value: Any, depth: int = 0) -> None:
    if depth > 30:
        raise _fail()
    if isinstance(value, dict):
        if not value:
            raise _fail()
        for key, item in value.items():
            if key == "reference" and (
                not isinstance(item, str)
                or re.fullmatch(r"[A-Za-z]+/[A-Za-z0-9.-]{1,64}", item) is None
            ):
                raise _fail()
            _raw_types(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise _fail()
        for item in value:
            _raw_types(item, depth + 1)
    elif type(value) not in (str, bool, int, float):
        raise _fail()


def validate_r4(resource: dict[str, Any]) -> None:
    try:
        _raw_types(resource)
        rtype = resource["resourceType"]
        for key, allowed in ENUMS.get(rtype, {}).items():
            if key in resource and resource[key] not in allowed:
                raise _fail()
        if rtype == "Condition":
            for field, (system, codes) in CONDITION_STATUS.items():
                if field not in resource:
                    continue
                if not isinstance(resource[field], dict):
                    raise _fail()
                coding = resource[field].get("coding", [])
                if (
                    not isinstance(coding, list)
                    or not coding
                    or any(
                        not isinstance(item, dict)
                        or item.get("system") != system
                        or item.get("code") not in codes
                        for item in coding
                    )
                ):
                    raise _fail()
        model = MODELS[rtype].parse_obj(resource)
        canonical = json.loads(model.json(exclude_none=True))
        _same(resource, canonical)
    except (ValidationError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise _fail() from exc
