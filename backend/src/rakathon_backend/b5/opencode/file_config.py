from __future__ import annotations

import json
from typing import Any

from rakathon_backend.b5.opencode.validation import (
    AZURE_API_KEY_HEADER,
    AZURE_API_KEY_REF,
    AZURE_BASE_URL,
    AZURE_PROVIDER_ID,
    PROVIDER_PACKAGE,
    validate_azure_base_url,
)

FILE_MODEL_CAPABILITIES: dict[str, Any] = {
    "tools": False,
    "input": ["text", "image"],
    "output": ["text"],
}
MIN_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS = 8192
DEFAULT_OUTPUT_TOKENS = 8192


def build_file_config_content(
    provider_id: str,
    model: str,
    base_url: str,
    *,
    max_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
) -> str:
    pid = provider_id.strip()
    if pid != AZURE_PROVIDER_ID:
        raise ValueError("file provider id must be the azure provider")
    normalized = validate_azure_base_url(base_url)
    if normalized != AZURE_BASE_URL:
        raise ValueError("azure provider base URL is not the trusted endpoint")
    name = model.strip()
    if not name or len(name) > 128:
        raise ValueError("model name is required")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not MIN_OUTPUT_TOKENS <= max_output_tokens <= MAX_OUTPUT_TOKENS
    ):
        raise ValueError("max output tokens are outside the limit")
    content: dict[str, Any] = {
        "providers": {
            pid: {
                "name": pid,
                "package": PROVIDER_PACKAGE,
                "settings": {"baseURL": normalized, "maxRetries": 0},
                "headers": {AZURE_API_KEY_HEADER: AZURE_API_KEY_REF},
                "models": {
                    name: {
                        "name": name,
                        "settings": {"maxOutputTokens": max_output_tokens, "maxRetries": 0},
                        "capabilities": FILE_MODEL_CAPABILITIES,
                    }
                },
            }
        },
        "permission": "deny",
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": pid, "effect": "allow"},
            {"action": "tool.use", "resource": "*", "effect": "deny"},
            {"action": "integration.use", "resource": "mcp:*", "effect": "deny"},
            {"action": "integration.use", "resource": "plugin:*", "effect": "deny"},
        ],
        "model": f"{pid}/{name}",
    }
    return json.dumps(content)
