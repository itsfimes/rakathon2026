from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rakathon_backend.runtime.auth_cmds import (
    cmd_auth_init,
    cmd_auth_user_add,
    cmd_auth_user_disable,
)
from rakathon_backend.runtime.auth_serve import cmd_auth_serve
from rakathon_backend.runtime.commands import (
    cmd_ai_check,
    cmd_bridge_serve,
    cmd_client,
    cmd_demo,
    cmd_health,
    cmd_init_db,
    cmd_keygen,
    cmd_serve,
    short_runtime,
)
from rakathon_backend.runtime.env_file import apply_env_file
from rakathon_backend.runtime.ingest import cmd_ingest_file
from rakathon_backend.runtime.screening_cmds import (
    cmd_screening_import,
    cmd_screening_init_db,
    cmd_screening_query,
    cmd_screening_validate,
)
from rakathon_backend.web.runtime import cmd_web_serve


def _add_env_file_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env-file",
        default=None,
        help="private 0600 KEY=VALUE file with RAKATHON_AI_*/AI_DISABLED/RAKATHON_IRIS_FHIR_* entries only",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rakathon-backend")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="run offline demo")
    demo.add_argument("--runtime-dir", default=None)
    _add_env_file_arg(demo)
    serve = sub.add_parser("serve", help="serve until signal")
    serve.add_argument("--runtime-dir", default=None)
    serve.add_argument("--storage", choices=("mock", "bridge", "iris-fhir"), default="mock")
    serve.add_argument("--ai", choices=("mock", "opencode", "direct"), default="mock")
    serve.add_argument("--watchdog-interval", type=float, default=1.0)
    serve.add_argument("--screening-source", default=None)
    _add_env_file_arg(serve)
    web = sub.add_parser("web-serve", help="read-only single-user development facade")
    web.add_argument("--runtime-dir", required=True)
    web.add_argument("--bind", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--proxy-key-file", required=True)
    web.add_argument("--frontend-origin", action="append", default=[])
    _add_env_file_arg(web)
    health = sub.add_parser("health", help="check health")
    health.add_argument("--runtime-dir", default=None)
    _add_env_file_arg(health)
    client = sub.add_parser("client", help="mock frontend client")
    client.add_argument("--runtime-dir", required=True)
    client.add_argument("--user", required=True)
    client.add_argument("--action", required=True)
    client.add_argument("--payload-json", default="{}")
    _add_env_file_arg(client)
    keygen = sub.add_parser("bridge-keygen", help="generate bridge key file")
    keygen.add_argument("--path", required=True)
    keygen.add_argument("--key-id", default=None)
    bserve = sub.add_parser("bridge-serve", help="serve encrypted bridge")
    bserve.add_argument("--bind", default="127.0.0.1")
    bserve.add_argument("--port", required=True, type=int)
    bserve.add_argument("--mock-storage", action="store_true")
    sub.add_parser("bridge-init-db", help="create iris task tables")
    ai_check = sub.add_parser("ai-check", help="validate local opencode AI config")
    _add_env_file_arg(ai_check)
    ingest = sub.add_parser("ingest-file", help="convert a local file in an ephemeral runtime")
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--user", required=True)
    ingest.add_argument("--ai", choices=("mock", "opencode", "direct"), default="mock")
    ingest.add_argument("--storage", choices=("mock", "iris-fhir"), default="mock")
    ingest.add_argument(
        "--patient-id", default=None, help="explicit trusted source patient association"
    )
    ingest.add_argument("--runtime-dir", default=None)
    ingest.add_argument("--output-file", default=None)
    _add_env_file_arg(ingest)
    sval = sub.add_parser(
        "screening-validate", help="validate a screening CSV/ZIP, aggregates only"
    )
    sval.add_argument("--source", required=True)
    sval.add_argument("--member", default=None)
    squery = sub.add_parser(
        "screening-query", help="bounded screening query, aggregates by default"
    )
    squery.add_argument("--runtime-dir", required=True)
    squery.add_argument("--user", required=True)
    squery.add_argument("--filters-json", default="{}")
    squery.add_argument("--projection", default="")
    squery.add_argument("--limit", type=int, default=100)
    squery.add_argument("--offset", type=int, default=0)
    squery.add_argument("--include-rows", action="store_true")
    _add_env_file_arg(squery)
    simp = sub.add_parser("screening-import", help="stream a screening source into IRIS via bridge")
    simp.add_argument("--source", required=True)
    simp.add_argument("--member", default=None)
    simp.add_argument("--batch-size", type=int, default=500)
    _add_env_file_arg(simp)
    sub.add_parser("screening-init-db", help="create iris screening table")
    ainit = sub.add_parser("auth-init", help="initialize private auth directory")
    ainit.add_argument("--auth-store", choices=("demo", "iris"), required=True)
    ainit.add_argument("--auth-dir", required=True)
    auadd = sub.add_parser("auth-user-add", help="provision a local auth user")
    auadd.add_argument("--auth-store", choices=("demo", "iris"), required=True)
    auadd.add_argument("--auth-dir", required=True)
    auadd.add_argument("--username", required=True)
    auadd.add_argument("--role", required=True)
    audis = sub.add_parser("auth-user-disable", help="disable a local auth user")
    audis.add_argument("--auth-store", choices=("demo", "iris"), required=True)
    audis.add_argument("--auth-dir", required=True)
    audis.add_argument("--user-id", required=True)
    aserve = sub.add_parser("auth-serve", help="serve authenticated UDS plus HTTP edge")
    aserve.add_argument("--auth-store", choices=("demo", "iris"), required=True)
    aserve.add_argument("--auth-dir", required=True)
    aserve.add_argument("--origin", required=True)
    aserve.add_argument("--allow-loopback-http", action="store_true")
    aserve.add_argument("--bind", default="127.0.0.1")
    aserve.add_argument("--port", type=int, default=8765)
    aserve.add_argument("--storage", choices=("mock", "iris-fhir"), default="mock")
    aserve.add_argument("--runtime-dir", default=None)
    aserve.add_argument("--demo-login-file", default=None)
    aserve.add_argument(
        "--assistant",
        "--assistant-enable",
        dest="assistant",
        action="store_true",
        help="explicit opt-in for direct AI assistant (requires provider env + kill gates)",
    )
    _add_env_file_arg(aserve)
    return parser


def _apply_env_file_arg(args: argparse.Namespace) -> int:
    env_file = getattr(args, "env_file", None)
    if not env_file:
        return 0
    try:
        apply_env_file(env_file)
    except (OSError, PermissionError, ValueError) as exc:
        print(json.dumps({"error": "env_file_rejected", "message": str(exc)}))
        return 2
    return 0


async def _async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rejected = _apply_env_file_arg(args)
    if rejected:
        return rejected
    if args.command == "demo":
        return await cmd_demo(short_runtime(args.runtime_dir))
    if args.command == "web-serve":
        return await cmd_web_serve(args)
    if args.command == "serve":
        return await cmd_serve(
            short_runtime(args.runtime_dir),
            str(args.storage),
            str(args.ai),
            float(args.watchdog_interval),
            getattr(args, "screening_source", None),
        )
    if args.command == "health":
        if not args.runtime_dir:
            print(json.dumps({"error": "runtime-dir is required for health"}))
            return 2
        return await cmd_health(Path(args.runtime_dir))
    if args.command == "client":
        return await cmd_client(args)
    if args.command == "bridge-keygen":
        return cmd_keygen(str(args.path), args.key_id)
    if args.command == "bridge-serve":
        return cmd_bridge_serve(str(args.bind), int(args.port), bool(args.mock_storage))
    if args.command == "bridge-init-db":
        return cmd_init_db()
    if args.command == "ai-check":
        return await cmd_ai_check()
    if args.command == "ingest-file":
        return await cmd_ingest_file(args)
    if args.command == "screening-validate":
        return cmd_screening_validate(args)
    if args.command == "screening-query":
        return await cmd_screening_query(args)
    if args.command == "screening-import":
        return cmd_screening_import(args)
    if args.command == "screening-init-db":
        return cmd_screening_init_db()
    if args.command == "auth-init":
        return cmd_auth_init(str(args.auth_store), str(args.auth_dir))
    if args.command == "auth-user-add":
        return cmd_auth_user_add(
            str(args.auth_store), str(args.auth_dir), str(args.username), str(args.role)
        )
    if args.command == "auth-user-disable":
        return cmd_auth_user_disable(str(args.auth_store), str(args.auth_dir), str(args.user_id))
    if args.command == "auth-serve":
        return await cmd_auth_serve(args)
    return 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
