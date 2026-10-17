from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from rakathon_backend.converter.extract import MAX_EXTRACT_BYTES
from rakathon_backend.converter.transcription import (
    TRANSCRIPT_ISSUE_CODES,
    TranscriptionError,
    build_extracted,
    build_transcription_prompt,
    parse_transcription,
)


def _payload(pages: list[dict[str, Any]], issues: list[str]) -> str:
    return json.dumps({"pages": pages, "issues": issues})


def test_prompt_states_count_codes_and_json_only() -> None:
    prompt = build_transcription_prompt(2)
    assert "2" in prompt
    assert "ONLY a JSON object" in prompt
    for code in TRANSCRIPT_ISSUE_CODES:
        assert code in prompt
    with pytest.raises(ValueError):
        build_transcription_prompt(0)
    with pytest.raises(ValueError):
        build_transcription_prompt(3)
    with pytest.raises(TypeError):
        build_transcription_prompt(True)


def test_parse_valid_result() -> None:
    raw = _payload([{"page": 1, "text": "Glucose 5.6 mmol/L"}], ["partial"])
    result = parse_transcription(raw, page_count=1)
    assert result.pages == ("Glucose 5.6 mmol/L",)
    assert result.issues == ("partial",)
    assert result.raw == raw


@pytest.mark.parametrize(
    "raw,count",
    [
        ("not json", 1),
        ('{"pages": [{"page": 1, "text": NaN}], "issues": []}', 1),
        ('{"pages": [{"page": 1, "text": "a"}], "issues": [], "extra": 1}', 1),
        ('{"pages": [{"page": 1, "text": "a", "x": 1}], "issues": []}', 1),
        ('{"pages": [{"page": 1, "text": "a"}, {"page": 1, "text": "b"}], "issues": []}', 2),
        ('{"pages": [{"page": 1, "text": "a"}, {"page": 3, "text": "b"}], "issues": []}', 2),
        ('{"pages": [{"page": 2, "text": "a"}, {"page": 1, "text": "b"}], "issues": []}', 2),
        ('{"pages": [{"page": true, "text": "a"}], "issues": []}', 1),
        ('{"pages": [{"page": 1, "text": 7}], "issues": []}', 1),
        ('{"pages": [{"page": 1, "text": "a\\u0001b"}], "issues": []}', 1),
        ('{"pages": [{"page": 1, "text": "a"}], "issues": ["nope"]}', 1),
        ('{"pages": [{"page": 1, "text": "a"}], "issues": [7]}', 1),
        ('{"pages": [{"page": 1, "text": "a"}]}', 1),
        ('{"pages": [{"page": 1, "text": "a"}], "issues": []}', 2),
        ("   ", 1),
    ],
)
def test_parse_rejects_bad_shapes(raw: str, count: int) -> None:
    with pytest.raises(TranscriptionError):
        parse_transcription(raw, page_count=count)


def test_parse_rejects_oversize_total() -> None:
    big = "x" * (MAX_EXTRACT_BYTES + 1)
    with pytest.raises(TranscriptionError) as excinfo:
        parse_transcription(_payload([{"page": 1, "text": big}], []), page_count=1)
    assert excinfo.value.code == "transcript_too_large"


def test_parse_rejects_blank_pages() -> None:
    raw = _payload([{"page": 1, "text": "   "}, {"page": 2, "text": ""}], [])
    with pytest.raises(TranscriptionError) as excinfo:
        parse_transcription(raw, page_count=2)
    assert excinfo.value.code == "transcript_no_text"


def test_build_extracted_labels_and_hashes() -> None:
    out = build_extracted(
        ("Glucose 5.6", "MRN: A-1"),
        source_sha256="s" * 64,
        suffix=".pdf",
        filename="report.pdf",
    )
    assert out.text == "[page 1]\nGlucose 5.6\n[page 2]\nMRN: A-1"
    assert out.pages == ("Glucose 5.6", "MRN: A-1")
    assert out.source_sha256 == "s" * 64
    assert out.extract_sha256 == hashlib.sha256(out.text.encode("utf-8")).hexdigest()
    assert out.suffix == ".pdf"
    assert out.filename == "report.pdf"


def test_build_extracted_rejects_blank_and_oversize() -> None:
    with pytest.raises(TranscriptionError):
        build_extracted([], source_sha256="s" * 64, suffix=".pdf", filename="r.pdf")
    with pytest.raises(TranscriptionError):
        build_extracted(["   "], source_sha256="s" * 64, suffix=".pdf", filename="r.pdf")
    big = "x" * (MAX_EXTRACT_BYTES + 1)
    with pytest.raises(TranscriptionError):
        build_extracted([big], source_sha256="s" * 64, suffix=".pdf", filename="r.pdf")
