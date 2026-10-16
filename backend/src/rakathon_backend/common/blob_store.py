from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

MAX_BLOB_BYTES = 262_144
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_TYPES = frozenset({"text/plain", "application/json", DOCX_MIME})
SCHEME_PREFIX = "ipc-blob://b1/"


class BlobError(ValueError):
    def __init__(self, code: str = "blob_error", message: str = "blob failure") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BlobNotFound(BlobError):
    def __init__(self, message: str = "blob reference not found") -> None:
        super().__init__("blob_not_found", message)


class BlobTooLarge(BlobError):
    def __init__(self, message: str = "blob exceeds size limit") -> None:
        super().__init__("blob_too_large", message)


class BlobUnsupportedType(BlobError):
    def __init__(self, message: str = "content type not supported") -> None:
        super().__init__("blob_unsupported_type", message)


@dataclass(frozen=True, slots=True)
class BlobRecord:
    blob_id: str
    content_type: str
    data: bytes
    synthetic: bool = True


class BlobStore:
    def __init__(self, *, max_bytes: int = MAX_BLOB_BYTES) -> None:
        self._max_bytes = max_bytes
        self._items: dict[str, BlobRecord] = {}
        self._lock = threading.Lock()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def put(self, data: bytes, content_type: str, *, synthetic: bool = True) -> str:
        if content_type not in ALLOWED_TYPES:
            raise BlobUnsupportedType()
        if len(data) > self._max_bytes:
            raise BlobTooLarge()
        blob_id = uuid.uuid4().hex
        with self._lock:
            self._items[blob_id] = BlobRecord(
                blob_id=blob_id, content_type=content_type, data=bytes(data), synthetic=synthetic
            )
        return f"{SCHEME_PREFIX}{blob_id}"

    def get(self, ref: str) -> BlobRecord:
        blob_id = parse_ref(ref)
        with self._lock:
            record = self._items.get(blob_id)
        if record is None:
            raise BlobNotFound()
        return record

    def delete(self, ref: str) -> bool:
        try:
            blob_id = parse_ref(ref)
        except BlobNotFound:
            return False
        with self._lock:
            return self._items.pop(blob_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def parse_ref(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(SCHEME_PREFIX):
        raise BlobNotFound()
    blob_id = ref[len(SCHEME_PREFIX) :]
    if not blob_id or len(blob_id) > 128:
        raise BlobNotFound()
    if not all(c in "0123456789abcdefABCDEF" for c in blob_id):
        raise BlobNotFound()
    return blob_id.lower()


def is_blob_ref(value: object) -> bool:
    return isinstance(value, str) and value.startswith(SCHEME_PREFIX)
