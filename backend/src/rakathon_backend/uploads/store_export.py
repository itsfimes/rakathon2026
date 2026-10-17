from __future__ import annotations

import io
import json
import zipfile as _zf
from typing import Any

from rakathon_backend.common.fhir import validate_bundle
from rakathon_backend.uploads.transcription_artifact import is_valid_transcription_bytes

MAX_EXPORT_BYTES = 12 * 1024 * 1024


def build_export_zip(
    original: bytes,
    result: bytes | None,
    bundle: bytes | None,
    provenance: bytes | None,
    events: Any,
    status: Any,
    sha256: Any,
    transcription: bytes | None = None,
) -> bytes | None:
    buf = io.BytesIO()
    with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as zf:
        zf.writestr("original.bin", original)
        zf.writestr(
            "result.json",
            result
            if result is not None
            else json.dumps({"status": status, "sha256": sha256}).encode(),
        )
        if bundle is not None:
            try:
                if validate_bundle(json.loads(bundle.decode("utf-8"))):
                    zf.writestr("bundle.json", bundle)
            except (ValueError, UnicodeDecodeError):
                pass
        if provenance is not None:
            zf.writestr("provenance.json", provenance)
        if transcription is not None and is_valid_transcription_bytes(transcription, sha256):
            zf.writestr("transcription.json", transcription)
        zf.writestr("attempts.json", json.dumps(events).encode())
    out = buf.getvalue()
    if len(out) > MAX_EXPORT_BYTES:
        return None
    return out
