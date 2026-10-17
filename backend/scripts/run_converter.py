from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import FrameType

IMAGE_NAME = "rakathon-converter:latest"
CONVERTER_MODULE = "rakathon_backend.converter.cli"
OUTER_TIMEOUT = 300.0


def _fail(message: str, code: str) -> int:
    sys.stderr.write(json.dumps({"error": code, "message": message}) + "\n")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_converter")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--secret-file", default=None)
    parser.add_argument("--allow-azure", action="store_true")
    parser.add_argument("--image", default=IMAGE_NAME)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--model", default="gpt-6-luna-dz-eu")
    parser.add_argument("--provider-id", default="rakathon-azure")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--recipe-cache", default=None)
    return parser


def backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _stage_context(dockerfile: Path, binary: str) -> Path:
    stage = Path(tempfile.mkdtemp(prefix="conv-ctx-"))
    shutil.copy2(dockerfile, stage / "Dockerfile")
    shutil.copy2(binary, stage / "opencode")
    os.chmod(stage / "opencode", 0o755)
    root = backend_root()
    shutil.copytree(root / "src", stage / "src")
    shutil.copy2(root / "pyproject.toml", stage / "pyproject.toml")
    shutil.copy2(root / "README.md", stage / "README.md")
    return stage


def build_image(image: str) -> int:
    root = backend_root()
    dockerfile = root / "docker" / "converter" / "Dockerfile"
    if not dockerfile.is_file():
        return _fail("dockerfile missing", "no_dockerfile")
    binary = shutil.which("opencode")
    if binary is None:
        return _fail("opencode binary missing on host", "no_binary")
    stage = _stage_context(dockerfile, binary)
    try:
        proc = subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(stage / "Dockerfile"),
                "--build-arg",
                "OPENCODE_VERSION=2.0.31",
                "-t",
                image,
                str(stage),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        sys.stdout.write(proc.stdout.decode("utf-8", "replace")[-4000:])
        return 0 if proc.returncode == 0 else 1
    except subprocess.TimeoutExpired:
        return _fail("docker build timed out", "build_timeout")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _resolve_recipe_cache(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if path.is_symlink():
        return None
    try:
        st = path.stat() if path.exists() else None
    except OSError:
        return None
    if st is not None and not stat.S_ISREG(st.st_mode):
        return None
    parent = path.parent
    if parent.is_symlink():
        return None
    return path


def run_container(args: argparse.Namespace) -> int:
    if shutil.which("docker") is None:
        return _fail("docker is not installed", "no_docker")
    input_path = Path(str(args.input))
    if input_path.is_symlink():
        return _fail("input is a symlink", "symlink_rejected")
    try:
        st = input_path.stat()
    except OSError:
        return _fail("input cannot be read", "unreadable_input")
    if not stat.S_ISREG(st.st_mode):
        return _fail("input is not a regular file", "special_file")
    output = Path(str(args.output))
    if output.is_symlink():
        return _fail("output is a symlink", "symlink_rejected")
    if output.exists() and any(output.iterdir()):
        return _fail("output directory is not empty", "output_not_empty")
    secret = args.secret_file
    if secret is not None:
        secret_path = Path(str(secret))
        if secret_path.is_symlink():
            return _fail("secret is a symlink", "secret_symlink")
        try:
            mode = secret_path.stat().st_mode
        except OSError:
            return _fail("secret cannot be read", "secret_unreadable")
        if mode & 0o077:
            return _fail("secret file must be 0600", "secret_permissions")
    recipe_cache = _resolve_recipe_cache(getattr(args, "recipe_cache", None))
    job = f"rakathon-conv-{os.getpid()}-{int(time.time())}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        job,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m,mode=1777",
        "--tmpfs",
        "/run:rw,noexec,nosuid,size=16m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    if args.offline or args.extract:
        cmd += ["--network", "none"]
    else:
        cmd += ["--network", "bridge"]
    inner_name = input_path.name
    cmd += ["-v", f"{input_path.resolve()}:/work/input/{inner_name}:ro"]
    out_abs = output.resolve() if output.exists() else (Path.cwd() / output).resolve()
    out_abs.mkdir(parents=True, exist_ok=True)
    cmd += ["-v", f"{out_abs}:/work/output:rw"]
    if recipe_cache is not None:
        recipe_cache.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not recipe_cache.exists():
            try:
                recipe_cache.write_text("{}", encoding="utf-8")
                os.chmod(recipe_cache, 0o600)
            except OSError:
                pass
        cmd += ["-v", f"{recipe_cache.resolve()}:/work/recipes/recipes.json:ro"]
        cmd += ["-e", "RAKATHON_RECIPE_CACHE_FILE=/work/recipes/recipes.json"]
        cmd += ["-e", "RAKATHON_RECIPE_CACHE_READ_ONLY=1"]
    inner = [
        "--input",
        f"/work/input/{inner_name}",
        "--output",
        "/work/output",
        "--provider-id",
        str(args.provider_id),
        "--model",
        str(args.model),
    ]
    if args.allow_azure and secret is not None and not args.offline:
        cmd += ["-v", f"{Path(str(secret)).resolve()}:/run/secrets/azure_api_key:ro"]
        inner += ["--allow-azure", "--secret-file", "/run/secrets/azure_api_key"]
    if args.extract:
        inner += ["--extract"]
    cmd += [str(args.image)] + inner
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
    except OSError:
        return _fail("launcher spawn failed", "spawn_failed")

    def _cleanup(signum: int, _frame: FrameType | None) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        with open(os.devnull, "w") as devnull:
            subprocess.run(["docker", "rm", "-f", job], stdout=devnull, stderr=devnull, check=False)
        raise SystemExit(130)

    old_int = signal.signal(signal.SIGINT, _cleanup)
    old_term = signal.signal(signal.SIGTERM, _cleanup)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=OUTER_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                stdout, stderr = proc.communicate()
            with open(os.devnull, "w") as devnull:
                subprocess.run(
                    ["docker", "rm", "-f", job], stdout=devnull, stderr=devnull, check=False
                )
            return _fail("converter outer timeout", "outer_timeout")
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    sys.stdout.write(stdout.decode("utf-8", "replace"))
    sys.stderr.write(stderr.decode("utf-8", "replace")[-2000:])
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if shutil.which("docker") is None:
        return _fail("docker is not installed", "no_docker")
    if args.build and not args.no_build:
        code = build_image(str(args.image))
        if code != 0:
            return code
    return run_container(args)


if __name__ == "__main__":
    raise SystemExit(main())
