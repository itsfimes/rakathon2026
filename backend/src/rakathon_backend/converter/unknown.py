from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path
from typing import Any

from rakathon_backend.converter.adaptive import AdaptiveError as _AErr
from rakathon_backend.converter.adaptive import AdaptiveManual as _AMan
from rakathon_backend.converter.adaptive import adapt_bytes
from rakathon_backend.converter.agent import AgentError, read_secret_file, run_model_once
from rakathon_backend.converter.detect import detect
from rakathon_backend.converter.extract import Extracted, ManualReviewNeeded
from rakathon_backend.converter.planner import (
    RecipeCache,
    metadata_for,
    parse_recipe_strict,
    planner_prompt,
    sample_for_prompt,
)

KNOWN_SUFFIXES = frozenset({".docx", ".txt", ".json", ".csv", ".pdf"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif"})
PLANNER_INFERENCE_TIMEOUT = 60.0
PLANNER_TOTAL_TIMEOUT = 90.0
_LAST_ADAPTIVE: dict[str, Any] = {}


def attach_adaptive(
    result: dict[str, Any], provenance: dict[str, Any], info: dict[str, Any]
) -> None:
    result["adaptive"] = {
        "newFormat": bool(info.get("newFormat", False)),
        "recipeReuse": bool(info.get("recipeReuse", False)),
        "plannerMode": str(info.get("plannerMode", "none")),
        "attempts": list(info.get("attempts", [])),
        "fingerprint": str(info.get("fingerprint", "")),
    }
    provenance["adaptive"] = dict(result["adaptive"])
    provenance["plannerMode"] = str(info.get("plannerMode", "none"))
    pending = info.get("pendingRecipe")
    if isinstance(pending, dict):
        steps = pending.get("steps")
        if isinstance(steps, list):
            provenance["pendingRecipe"] = {"version": 1, "steps": steps}


def unknown_flow(
    args: argparse.Namespace, raw: bytes, suffix: str, filename: str
) -> tuple[Extracted, dict[str, Any]]:
    detected = detect(raw, suffix, filename)
    cache_path = os.environ.get("RAKATHON_RECIPE_CACHE_FILE", "").strip()
    cache = RecipeCache(Path(cache_path)) if cache_path else RecipeCache(None)
    cached = cache.get(detected.fingerprint)
    info: dict[str, Any] = {
        "newFormat": True,
        "recipeReuse": False,
        "plannerMode": "fallback",
        "attempts": [],
        "fingerprint": detected.fingerprint,
    }
    if cached is not None:
        try:
            adapted = adapt_bytes(raw, suffix, filename, recipe=cached, recipe_reuse=True)
        except (_AErr, _AMan):
            pass
        else:
            info["recipeReuse"] = True
            info["plannerMode"] = adapted.planner_mode
            info["attempts"] = [e.code + ":" + e.status for e in adapted.attempts]
            info["attempts"].insert(0, "cache_reuse:ok")
            out = Extracted(
                text=adapted.text,
                pages=adapted.pages,
                source_sha256=adapted.source_sha256,
                extract_sha256=adapted.extract_sha256,
                suffix=suffix,
                filename=filename,
            )
            _LAST_ADAPTIVE.clear()
            _LAST_ADAPTIVE.update(info)
            return (out, info)
        info["attempts"].append("cache_reuse:stale")
    if bool(getattr(args, "allow_azure", False)) and str(getattr(args, "secret_file", "") or ""):
        try:
            api_key = read_secret_file(str(args.secret_file))
        except AgentError:
            api_key = ""
        if api_key:
            meta = metadata_for(raw, suffix, detected.fingerprint, detected.category)
            try:
                planned = run_model_once(
                    planner_prompt(meta, sample_for_prompt(raw)),
                    provider_id=str(args.provider_id),
                    model=str(args.model),
                    base_url=str(args.base_url),
                    api_key=api_key,
                    startup_timeout=float(args.startup_timeout),
                    inference_timeout=PLANNER_INFERENCE_TIMEOUT,
                    total_timeout=PLANNER_TOTAL_TIMEOUT,
                )
                recipe = parse_recipe_strict(planned)
            except (AgentError, ValueError, TypeError, OSError, RuntimeError):
                recipe = None
            if recipe is not None:
                try:
                    adapted = adapt_bytes(raw, suffix, filename, recipe=recipe)
                except (_AErr, _AMan):
                    info["attempts"].append("planner_recipe:failed")
                else:
                    info["plannerMode"] = "planner"
                    info["attempts"] = [e.code + ":" + e.status for e in adapted.attempts]
                    with_adapt = Extracted(
                        text=adapted.text,
                        pages=adapted.pages,
                        source_sha256=adapted.source_sha256,
                        extract_sha256=adapted.extract_sha256,
                        suffix=suffix,
                        filename=filename,
                    )
                    info["pendingRecipe"] = recipe
                    _LAST_ADAPTIVE.clear()
                    _LAST_ADAPTIVE.update(info)
                    return (with_adapt, info)
    try:
        adapted = adapt_bytes(raw, suffix, filename)
    except _AMan as exc:
        info["attempts"].append("planner_fallback:no-agent")
        _LAST_ADAPTIVE.clear()
        _LAST_ADAPTIVE.update(info)
        raise ManualReviewNeeded(exc.code, exc.message) from exc
    info["plannerMode"] = adapted.planner_mode
    info["attempts"] = [e.code + ":" + e.status for e in adapted.attempts]
    info["attempts"].append("planner_fallback:no-agent")
    _LAST_ADAPTIVE.clear()
    _LAST_ADAPTIVE.update(info)
    out = Extracted(
        text=adapted.text,
        pages=adapted.pages,
        source_sha256=adapted.source_sha256,
        extract_sha256=adapted.extract_sha256,
        suffix=suffix,
        filename=filename,
    )
    return (out, info)


def read_raw_for_unknown(raw_path: str) -> tuple[bytes, str, str] | None:
    path = Path(raw_path)
    if path.is_symlink():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_size > 5 * 1024 * 1024 or st.st_size == 0:
        return None
    suffix = path.suffix.lower()
    if suffix in KNOWN_SUFFIXES or suffix in IMAGE_SUFFIXES:
        return None
    try:
        return (path.read_bytes(), suffix, path.name)
    except OSError:
        return None


def last_adaptive() -> dict[str, Any]:
    return dict(_LAST_ADAPTIVE)


def clear_last_adaptive() -> None:
    _LAST_ADAPTIVE.clear()
