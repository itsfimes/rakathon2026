from __future__ import annotations

import hashlib
import io
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.converter.extract import extract_file
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.suffix import safe_suffix
from rakathon_backend.uploads.worker import UploadWorker


def _store(tmp_path: Path) -> UploadStore:
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    keys = generate_key_file(d / "store.key")
    return UploadStore(d, keys)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _ooxml_bytes() -> bytes:
    return _zip_bytes(
        {
            "[Content_Types].xml": b"<Types></Types>",
            "word/document.xml": (
                b"<w:document><w:body><w:p><w:r><w:t>synthetic ward note</w:t>"
                b"</w:r></w:p></w:body></w:document>"
            ),
        }
    )


def _xml_zip_bytes() -> bytes:
    return _zip_bytes(
        {
            "report/a.xml": b"<note><to>ward</to><body>synthetic note</body></note>",
            "notes/b.txt": b"synthetic plain member with readable words",
        }
    )


def _review_runner(src: Path, out: Path, allow: bool) -> int:
    _ = allow
    try:
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(
            {
                "status": "manual-review",
                "bundle": None,
                "issues": [{"code": "unknown_no_extract", "message": "no decoder"}],
                "evidence": [],
                "needsReview": True,
                "writeEligible": False,
                "persistence": "not-written",
                "model": {"providerId": "p", "model": "m", "present": False},
                "source": {"sha256": sha},
                "adaptive": {
                    "newFormat": True,
                    "recipeReuse": False,
                    "plannerMode": "fallback",
                    "attempts": ["planner_fallback:no-agent"],
                    "fingerprint": "fp",
                },
            }
        )
    )
    (out / "provenance.json").write_text(
        json.dumps({"sourceSha256": sha, "adaptive": {"plannerMode": "fallback"}})
    )
    return 0


def _complete_runner(
    src: Path, out: Path, allow: bool, *, source_sha: str | None, present: bool
) -> int:
    _ = allow
    try:
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    out.mkdir(parents=True, exist_ok=True)
    source: dict[str, Any] = {} if source_sha is None else {"sha256": source_sha}
    (out / "result.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "bundle": None,
                "issues": [],
                "evidence": [],
                "needsReview": True,
                "writeEligible": False,
                "persistence": "not-written",
                "model": {"providerId": "p", "model": "m", "present": present},
                "source": source,
                "adaptive": {
                    "newFormat": False,
                    "recipeReuse": False,
                    "plannerMode": "none",
                    "attempts": [],
                    "fingerprint": "",
                },
            }
        )
    )
    (out / "provenance.json").write_text(json.dumps({"sourceSha256": sha}))
    return 0


def test_zip_of_xml_never_maps_to_docx(tmp_path: Path) -> None:
    raw = _xml_zip_bytes()
    assert safe_suffix("data.zip", raw) != ".docx"
    store = _store(tmp_path)
    seen: dict[str, str] = {}

    def runner(src: Path, out: Path, allow: bool) -> int:
        seen["suffix"] = src.suffix
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    job = store.enqueue("u1", "SYN-1", "data.zip", raw)
    worker._convert(job["id"])
    assert seen.get("suffix") != ".docx"
    back = store.get(job["id"])
    assert back is not None and back["status"] == "manual-review"


def test_generic_zip_named_docx_maps_to_bin(tmp_path: Path) -> None:
    _ = tmp_path
    assert safe_suffix("report.docx", _xml_zip_bytes()) == ".bin"


def test_renamed_docx_uses_docx(tmp_path: Path) -> None:
    _ = tmp_path
    assert safe_suffix("report.dat", _ooxml_bytes()) == ".docx"


def test_cp1250_txt_uses_bounded_decode(tmp_path: Path) -> None:
    text = "Příliš žluťoučký kůň úpěl ďábelské ódy na lůžku"
    target = tmp_path / "nota.txt"
    target.write_bytes(text.encode("cp1250"))
    extracted = extract_file(str(target))
    assert extracted.suffix == ".txt"
    assert "žluťoučký" in extracted.text


def test_complete_rejects_missing_source_sha(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def runner(src: Path, out: Path, allow: bool) -> int:
        return _complete_runner(src, out, allow, source_sha=None, present=True)

    worker = UploadWorker(store, runner=runner)
    job = store.enqueue("u1", "SYN-1", "note.hl7", b"readable synthetic ward note words here")
    worker._convert(job["id"])
    back = store.get(job["id"])
    assert back is not None and back["status"] == "failed"
    assert back.get("reason") == "sha_mismatch"


def test_complete_rejects_model_not_present(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def runner(src: Path, out: Path, allow: bool) -> int:
        try:
            sha = hashlib.sha256(src.read_bytes()).hexdigest()
        except OSError:
            sha = ""
        return _complete_runner(src, out, allow, source_sha=sha, present=False)

    worker = UploadWorker(store, runner=runner)
    job = store.enqueue("u1", "SYN-1", "note.hl7", b"readable synthetic ward note words here")
    worker._convert(job["id"])
    back = store.get(job["id"])
    assert back is not None and back["status"] == "failed"
    assert back.get("reason") == "bad_envelope"


def test_dotted_nonce_envelope_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(secrets, "token_bytes", lambda n: b"." * n)
    job = store.enqueue("u1", "SYN-1", "nota.txt", b"readable synthetic ward note words here")
    assert store.read_original(job["id"]) == b"readable synthetic ward note words here"
    store.write_result_blob(job["id"], "result", b'{"status":"manual-review"}')
    assert store.read_result_blob(job["id"], "result") == b'{"status":"manual-review"}'
