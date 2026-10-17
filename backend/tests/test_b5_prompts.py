from typing import Any

import pytest

from rakathon_backend.b5.prompts import (
    TRANSLATE_PROMPT,
    build_complete_prompt,
    build_translate_prompt,
)
from rakathon_backend.common.errors import ContractError


def test_build_translate_prompt() -> None:
    source = "Nález: hodnota 0, stav false.\n"
    assert build_translate_prompt(source) == TRANSLATE_PROMPT + source
    assert TRANSLATE_PROMPT.startswith("Translate the supplied source")
    assert TRANSLATE_PROMPT.endswith("SOURCE DATA:\n")
    assert build_translate_prompt("") == TRANSLATE_PROMPT


def test_build_complete_prompt_without_context() -> None:
    message = "Vysvětli výsledek.\n"
    assert build_complete_prompt(message) == message
    assert build_complete_prompt(message, clinical_context="") == message
    assert build_complete_prompt("") == ""


def test_build_complete_prompt_with_context() -> None:
    assert build_complete_prompt(
        "Vysvětli výsledek.", clinical_context="Rok: 2020\nHodnota: 0"
    ) == (
        "=== KLINICKÝ KONTEXT ===\n"
        "Rok: 2020\nHodnota: 0\n"
        "=== KONEC KLINICKÉHO KONTEXTU ===\n\n"
        "Vysvětli výsledek."
    )


@pytest.mark.parametrize("value", [None, 0, False, b"text", [], {}])
def test_build_translate_prompt_rejects_non_strings(value: Any) -> None:
    with pytest.raises(ContractError) as exc:
        build_translate_prompt(value)
    assert exc.value.code == "ai_bad_input"


@pytest.mark.parametrize("value", [None, 0, False, b"text", [], {}])
@pytest.mark.parametrize("field", ["user_message", "clinical_context"])
def test_build_complete_prompt_rejects_non_strings(value: Any, field: str) -> None:
    with pytest.raises(ContractError) as exc:
        if field == "user_message":
            build_complete_prompt(value)
        else:
            build_complete_prompt("Dotaz", clinical_context=value)
    assert exc.value.code == "ai_bad_input"
