from __future__ import annotations

import pytest

from rakathon_backend.cli import build_parser


def test_serve_parser_has_ai_and_watchdog() -> None:
    args = build_parser().parse_args(["serve", "--ai", "direct", "--watchdog-interval", "2.5"])
    assert args.ai == "direct"
    assert float(args.watchdog_interval) == 2.5
    defaults = build_parser().parse_args(["serve"])
    assert defaults.ai == "mock"
    assert float(defaults.watchdog_interval) == 1.0


def test_serve_parser_rejects_removed_ai_mode() -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["serve", "--ai", "opencode"])
    assert exc.value.code == 2


def test_ai_check_subcommand_removed() -> None:
    parser = build_parser()
    assert "ai-check" not in parser.format_help()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["ai-check"])
    assert exc.value.code == 2
