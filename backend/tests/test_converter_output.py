from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.converter.extract import Extracted
from rakathon_backend.converter.output import (
    OutputError,
    assemble_result,
    check_evidence,
    manual_result,
    parse_model_output_strict,
    write_outputs,
)

TEXT = "[page 1]\nPAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL"


def _extracted() -> Extracted:
    return Extracted(
        text=TEXT,
        pages=("PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL",),
        source_sha256=hashlib.sha256(b"raw").hexdigest(),
        extract_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
        suffix=".txt",
        filename="doc.txt",
    )


def _patient() -> dict[str, Any]:
    return {"resourceType": "Patient", "id": "p1"}


def _docref() -> dict[str, Any]:
    return {
        "resourceType": "DocumentReference",
        "id": "d1",
        "status": "current",
        "content": [{"attachment": {"data": "aGVsbG8="}}],
    }


def _bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"resource": _patient(), "request": {"method": "PUT", "url": "Patient/p1"}},
            {
                "resource": _docref(),
                "request": {"method": "PUT", "url": "DocumentReference/d1"},
            },
        ],
    }


def _envelope(**overrides: Any) -> str:
    doc: dict[str, Any] = {
        "status": "complete",
        "bundle": _bundle(),
        "issues": [],
        "evidence": [
            {
                "resourceType": "Patient",
                "id": "p1",
                "sourcePage": 1,
                "literalQuote": "PAT ZEBRA SYN-000001",
                "field": "/id",
            },
            {
                "resourceType": "DocumentReference",
                "id": "d1",
                "sourcePage": 1,
                "literalQuote": "GLUCOSE 102 mg/dL",
                "field": "/content/0/attachment/data",
            },
        ],
    }
    doc.update(overrides)
    return json.dumps(doc)


def test_valid_output_passes_strict_parse_and_evidence() -> None:
    parsed = parse_model_output_strict(_envelope())
    checked = check_evidence(parsed, _extracted(), conflict=False)
    assert checked["status"] == "complete"
    assert checked["bundle"] is not None


def test_fences_rejected() -> None:
    with pytest.raises(OutputError) as caught:
        parse_model_output_strict("```json\n" + _envelope() + "\n```")
    assert caught.value.code == "fenced_output"


def test_nan_constant_rejected() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict('{"status": NaN}')


def test_duplicate_keys_rejected() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict('{"status": "complete", "status": "complete"}')


def test_extra_envelope_keys_rejected() -> None:
    with pytest.raises(OutputError) as caught:
        parse_model_output_strict(_envelope(provenance={"by": "model"}))
    assert caught.value.code == "bad_envelope"


def test_bundle_on_manual_review_rejected() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict(_envelope(status="manual-review"))


def test_null_bundle_on_complete_rejected() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict(_envelope(bundle=None))


def test_unclosed_reference_rejected() -> None:
    bundle = _bundle()
    entries = bundle["entry"]
    assert isinstance(entries, list)
    first = entries[0]
    assert isinstance(first, dict)
    resource = first["resource"]
    assert isinstance(resource, dict)
    resource["managingOrganization"] = {"reference": "Organization/missing"}
    with pytest.raises(OutputError) as caught:
        parse_model_output_strict(_envelope(bundle=bundle))
    assert caught.value.code == "fhir_rejected"


def test_quote_absent_from_page_rejected() -> None:
    with pytest.raises(OutputError) as caught:
        parsed = parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 1,
                        "literalQuote": "NOT IN EXTRACT VALUES",
                        "field": "/id",
                    },
                    {
                        "resourceType": "DocumentReference",
                        "id": "d1",
                        "sourcePage": 1,
                        "literalQuote": "GLUCOSE 102 mg/dL",
                        "field": "/content/0/attachment/data",
                    },
                ]
            )
        )
        check_evidence(parsed, _extracted(), conflict=False)
    assert caught.value.code == "quote_not_found"


def test_unknown_source_page_rejected() -> None:
    with pytest.raises(OutputError):
        parsed = parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 9,
                        "literalQuote": "PAT ZEBRA SYN-000001",
                        "field": "/id",
                    },
                    {
                        "resourceType": "DocumentReference",
                        "id": "d1",
                        "sourcePage": 1,
                        "literalQuote": "GLUCOSE 102 mg/dL",
                        "field": "/content/0/attachment/data",
                    },
                ]
            )
        )
        check_evidence(parsed, _extracted(), conflict=False)


def test_missing_clinical_evidence_rejected() -> None:
    with pytest.raises(OutputError) as caught:
        parsed = parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 1,
                        "literalQuote": "PAT ZEBRA SYN-000001",
                        "field": "/id",
                    },
                ]
            )
        )
        check_evidence(parsed, _extracted(), conflict=False)
    assert caught.value.code == "missing_evidence"


def test_bad_field_pointer_rejected() -> None:
    with pytest.raises(OutputError):
        parsed = parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 1,
                        "literalQuote": "PAT ZEBRA SYN-000001",
                        "field": "/nope/missing",
                    },
                    {
                        "resourceType": "DocumentReference",
                        "id": "d1",
                        "sourcePage": 1,
                        "literalQuote": "GLUCOSE 102 mg/dL",
                        "field": "/content/0/attachment/data",
                    },
                ]
            )
        )
        check_evidence(parsed, _extracted(), conflict=False)


def test_conflict_forces_manual_review_without_bundle() -> None:
    parsed = parse_model_output_strict(_envelope())
    checked = check_evidence(parsed, _extracted(), conflict=True)
    assert checked["status"] == "manual-review"
    assert checked["bundle"] is None
    assert any(i["code"] == "conflicting_identity" for i in checked["issues"])


def test_assemble_attaches_source_and_never_eligible() -> None:
    parsed = parse_model_output_strict(_envelope())
    checked = check_evidence(parsed, _extracted(), conflict=False)
    result, bundle, provenance = assemble_result(
        checked,
        _extracted(),
        model_present=True,
        provider_id="rakathon-azure",
        model="gpt-6-luna-dz-eu",
        runtime_s=1.0,
    )
    assert result["needsReview"] is True
    assert result["writeEligible"] is False
    assert result["persistence"] == "not-written"
    assert bundle is not None
    meta = bundle.get("meta")
    assert isinstance(meta, dict)
    assert meta["source"] == "urn:sha256:" + _extracted().source_sha256
    assert provenance["extractSha256"] == _extracted().extract_sha256


def test_manual_result_shape_without_source() -> None:
    result, bundle, provenance = manual_result(
        "image_no_ocr",
        "needs human",
        None,
        provider_id="rakathon-azure",
        model="gpt-6-luna-dz-eu",
        runtime_s=0.5,
    )
    assert result["status"] == "manual-review"
    assert bundle is None
    assert result["bundle"] is None
    assert provenance["modelPresent"] is False


def test_write_outputs_layout_and_modes(tmp_path: Path) -> None:
    outdir = tmp_path / "out"
    result, bundle, provenance = manual_result(
        "azure_not_opted_in",
        "no key",
        _extracted(),
        provider_id="rakathon-azure",
        model="gpt-6-luna-dz-eu",
        runtime_s=0.1,
    )
    write_outputs(outdir, result, bundle, provenance)
    assert (outdir / "result.json").is_file()
    assert (outdir / "provenance.json").is_file()
    assert not (outdir / "bundle.json").exists()
    assert stat.S_IMODE((outdir / "result.json").stat().st_mode) == 0o600


def test_write_outputs_refuses_nonempty(tmp_path: Path) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "stale.json").write_text("{}", encoding="utf-8")
    result, bundle, provenance = manual_result(
        "x", "y", None, provider_id="p", model="m", runtime_s=0.0
    )
    with pytest.raises(OutputError) as caught:
        write_outputs(outdir, result, bundle, provenance)
    assert caught.value.code == "output_not_empty"
    assert (outdir / "stale.json").is_file()


def test_write_outputs_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    result, bundle, provenance = manual_result(
        "x", "y", None, provider_id="p", model="m", runtime_s=0.0
    )
    with pytest.raises(OutputError):
        write_outputs(link, result, bundle, provenance)


def test_short_quote_rejected() -> None:
    with pytest.raises(OutputError) as caught:
        parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 1,
                        "literalQuote": "short",
                        "field": "/id",
                    }
                ]
            )
        )
    assert caught.value.code == "bad_evidence"


def test_clinical_evidence_requires_field() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict(
            _envelope(
                evidence=[
                    {
                        "resourceType": "Patient",
                        "id": "p1",
                        "sourcePage": 1,
                        "literalQuote": "PAT ZEBRA SYN-000001",
                    }
                ]
            )
        )


def test_outcome_bundle_rejected() -> None:
    outcome = {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "invalid"}],
    }
    with pytest.raises(OutputError) as caught:
        parse_model_output_strict(_envelope(bundle=outcome))
    assert caught.value.code in ("outcome_rejected", "fhir_rejected")


def test_complete_with_issues_rejected() -> None:
    with pytest.raises(OutputError):
        parse_model_output_strict(_envelope(issues=[{"code": "x", "message": "y"}]))
