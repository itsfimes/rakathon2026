from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.web.assistant_context import FIELD_SOURCES, ROLES, SnapshotBindings, canonical
from rakathon_backend.web.contracts import Client, WebError
from rakathon_backend.web.clinical_context import COMMON_FIELDS
from rakathon_backend.web.projection import ID

DEADLINE = 80


def validate_request(value: Any) -> dict[str, Any]:
    bad = WebError(400, "bad_request", "Invalid assistant request")
    if not isinstance(value, dict) or set(value) - {"role", "text", "context", "binding"}:
        raise bad
    if (
        value.get("role") not in ROLES
        or not isinstance(value.get("text"), str)
        or not value["text"].strip()
        or len(value["text"]) > 1000
    ):
        raise bad
    if ("context" in value) != ("binding" in value):
        raise bad
    if "context" in value:
        context, binding = value["context"], value["binding"]
        if (
            not isinstance(context, dict)
            or set(context) != {"role", "fields"}
            or context["role"] != value["role"]
        ):
            raise bad
        fields = context["fields"]
        if not isinstance(fields, list) or not 1 <= len(fields) <= 32:
            raise bad
        total = 0
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"key", "source", "value"}:
                raise bad
            if (
                not isinstance(field["key"], str)
                or FIELD_SOURCES.get(field["key"]) != field["source"]
                or not isinstance(field["value"], str)
                or not field["value"].strip()
                or len(field["value"]) > 320
            ):
                raise bad
            if value["role"] == "koordinator" and field["key"] not in COMMON_FIELDS:
                raise bad
            total += len(field["value"])
        if total > 4000 or not isinstance(binding, dict) or set(binding) != {"caseId", "token"}:
            raise bad
        if (
            not isinstance(binding["caseId"], str)
            or ID.fullmatch(binding["caseId"]) is None
            or not isinstance(binding["token"], str)
            or len(binding["token"]) > 90
        ):
            raise bad
    return value


class WebAssistant:
    def __init__(
        self,
        client: Client,
        read_case: Callable[[str], Awaitable[tuple[int, dict[str, Any]]]],
        *,
        binding_key: bytes | None = None,
        binding_clock: Callable[[], float] | None = None,
    ) -> None:
        self.client = client
        self.read_case = read_case
        if binding_clock is not None:
            self.bindings = SnapshotBindings(binding_clock, key=binding_key)
        elif binding_key is not None:
            self.bindings = SnapshotBindings(key=binding_key)
        else:
            self.bindings = SnapshotBindings()
        self.busy = False

    async def send(self, raw: Any) -> tuple[int, dict[str, Any]]:
        request = validate_request(raw)
        if self.busy:
            raise WebError(429, "unavailable", "Assistant is busy")
        self.busy = True
        try:
            async with asyncio.timeout(DEADLINE):
                return await self._send(request)
        except WebError:
            raise
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
            raise WebError(503, "unavailable", "Assistant unavailable") from exc
        finally:
            self.busy = False

    async def _send(self, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        context = None
        sources: list[str] = []
        if "context" in request:
            binding = request["binding"]
            _, case = await self.read_case(binding["caseId"])
            if not self.bindings.matches(
                case, request["role"], binding["token"], request["context"]
            ):
                raise WebError(409, "stale_context", "Reload the selected case context")
            context = request["context"]
            sources = list(dict.fromkeys(field["source"] for field in context["fields"]))
        data = {"role": request["role"], "message": request["text"], "context": context}
        prompt = canonical(data).decode()
        envelope = new_envelope(
            source="frontend:web-assistant",
            target="b4",
            action="ai.complete",
            data_kind=DataKind.PROPRIETARY,
            payload={"prompt": prompt},
            user_id="web-assistant",
        )
        reply: Envelope = await self.client.call(envelope, expect_source="b4")
        text = reply.payload.get("answer")
        if (
            reply.payload.get("mode") != "direct"
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 6000
        ):
            raise WebError(503, "unavailable", "Assistant response invalid")
        return 200, {"provenance": "server", "text": text, "sources": sources}
