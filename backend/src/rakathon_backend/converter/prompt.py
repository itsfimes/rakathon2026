from __future__ import annotations

from pathlib import Path

from rakathon_backend.b5.opencode.validation import MAX_PROMPT_CHARS
from rakathon_backend.converter.extract import Extracted


def prompt_path() -> Path:
    return Path(__file__).with_name("prompt.md")


def build_prompt(extracted: Extracted) -> str:
    template = prompt_path().read_text(encoding="utf-8")
    prompt = template + extracted.text + "\n"
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("converter prompt exceeds the model prompt cap")
    return prompt
