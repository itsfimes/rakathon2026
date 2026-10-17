from __future__ import annotations

from typing import Any

from rakathon_backend.b5.opencode.validation import MAX_RESPONSE_BYTES
from rakathon_backend.common.errors import TransportError


class FilePromptError(TransportError):
    def __init__(
        self,
        code: str = "transport_error",
        message: str = "transport failure",
        *,
        metadata: dict[str, Any] | None = None,
        partial_text: str | None = None,
    ) -> None:
        super().__init__(code=code, message=message, metadata=metadata)
        if not isinstance(partial_text, str) or not partial_text.strip():
            self.partial_text: str | None = None
        else:
            raw = partial_text.encode("utf-8")
            if len(raw) > MAX_RESPONSE_BYTES:
                raw = raw[:MAX_RESPONSE_BYTES]
                decoded = raw.decode("utf-8", "ignore")
            else:
                decoded = partial_text
            self.partial_text = decoded if decoded.strip() else None


def collect_own_text(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for chunk in content:
        if not isinstance(chunk, dict):
            return None
        kind = chunk.get("type")
        if kind == "text":
            piece = chunk.get("text")
            if not isinstance(piece, str):
                return None
            parts.append(piece)
        elif kind == "tool":
            continue
        else:
            continue
    joined = "".join(parts)
    return joined if joined.strip() else None
