from __future__ import annotations

import base64
import contextlib
import hmac
import ipaddress
import os
import re
import secrets
import stat
import urllib.parse
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path

from rakathon_backend.common.errors import ContractError

PROXY_HEADER = "x-rakathon-proxy-key"
LOGIN_HEADER = "x-rakathon-auth"
LOGIN_HEADER_VALUE = "1"
CSRF_HEADER = "x-csrf-token"
ORIGIN_HEADER = "origin"
COOKIE_PROD = "__Host-rakathon_session"
COOKIE_LOOPBACK = "rakathon_session_loopback"
MAX_BODY_BYTES = 16 * 1024
MAX_REVIEW_BODY_BYTES = 768 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_BYTES = 12 * 1024 * 1024
MAX_PATH_CHARS = 2048
MAX_HEADER_CHARS = 8192
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
SESSION_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SIZE_CAP = 256


def _is_loopback_host(host: str) -> bool:
    text = host.strip().strip("[]").lower()
    if text in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def parse_origin(origin: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urllib.parse.urlparse(origin.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname or parsed.fragment or parsed.username or parsed.password:
        return None
    return (parsed.scheme, parsed.hostname.lower(), parsed.port)


def is_loopback_origin(origin: str) -> bool:
    parsed = parse_origin(origin)
    if parsed is None:
        return False
    scheme, host, port = parsed
    if scheme != "http" or port is None:
        return False
    return _is_loopback_host(host)


def origin_host(origin: str) -> str:
    parsed = parse_origin(origin)
    if parsed is None:
        return ""
    return parsed[1]


def check_host_authority(host_value: str, configured_origin: str) -> bool:
    text = host_value.strip()
    if not text or len(text) > 256:
        return False
    bare = text.split(",")[0].strip().split(" ")[0].strip()
    if "," in text:
        return False
    name = bare.rsplit(":", 1)[0].strip("[] ") if ":" in bare else bare
    if not name:
        return False
    if _is_loopback_host(name):
        return True
    return name.lower() == origin_host(configured_origin).lower()


def listener_authority(bind: str, port: int) -> str:
    host = bind.strip().strip("[]").lower()
    if host == "localhost":
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{int(port)}"
    return f"{host}:{int(port)}"


def normalize_authority(value: str) -> str | None:
    text = value.strip().lower()
    if not text or len(text) > 256 or "," in text or " " in text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        rest = text[end + 1 :]
        if not rest.startswith(":") or not rest[1:].isdigit():
            return None
        return text
    if text.count(":") != 1:
        return None
    host, port = text.rsplit(":", 1)
    if not host or not port.isdigit():
        return None
    return text


def check_host_allowlist(host_value: str, allowed: frozenset[str]) -> bool:
    normalized = normalize_authority(host_value)
    if normalized is None:
        return False
    return normalized in allowed


@dataclass(frozen=True)
class WebConfig:
    origin: str
    loopback_http: bool
    cookie_name: str
    secure_cookie: bool

    @staticmethod
    def build(origin: str, allow_loopback_http: bool) -> WebConfig:
        parsed = parse_origin(origin)
        if parsed is None:
            raise ContractError(code="not_configured", message="origin is not configured")
        scheme, host, port = parsed
        if scheme == "http":
            if port is None:
                raise ContractError(code="not_configured", message="origin needs a port")
            loopback = _is_loopback_host(host)
            if not (allow_loopback_http and loopback):
                raise ContractError(code="not_configured", message="http needs loopback")
            return WebConfig(
                origin=origin.strip(),
                loopback_http=True,
                cookie_name=COOKIE_LOOPBACK,
                secure_cookie=False,
            )
        return WebConfig(
            origin=origin.strip(),
            loopback_http=False,
            cookie_name=COOKIE_PROD,
            secure_cookie=True,
        )


def _proxy_parent_ok(path: Path) -> None:
    try:
        parent_stat = path.parent.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="proxy key unavailable") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise ContractError(code="not_configured", message="proxy key unavailable")
    if parent_stat.st_uid != os.getuid():
        raise ContractError(code="not_configured", message="proxy key unavailable")
    if (parent_stat.st_mode & 0o077) != 0:
        raise ContractError(code="not_configured", message="proxy key unavailable")


def load_proxy_key(path: Path) -> str:
    target = Path(path)
    _proxy_parent_ok(target)
    if target.is_symlink():
        raise ContractError(code="not_configured", message="proxy key unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(target), flags)
    except OSError as exc:
        raise ContractError(code="not_configured", message="proxy key unavailable") from exc
    try:
        try:
            info = os.fstat(fd)
        except OSError as exc:
            raise ContractError(code="not_configured", message="proxy key unavailable") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(code="not_configured", message="proxy key unavailable")
        if info.st_uid != os.getuid():
            raise ContractError(code="not_configured", message="proxy key unavailable")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ContractError(code="not_configured", message="proxy key unavailable")
        if info.st_size <= 0 or info.st_size > SIZE_CAP:
            raise ContractError(code="not_configured", message="proxy key unavailable")
        chunks: list[bytes] = []
        remaining = SIZE_CAP + 1
        while remaining > 0:
            try:
                part = os.read(fd, remaining)
            except OSError as exc:
                raise ContractError(code="not_configured", message="proxy key unavailable") from exc
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        raw_bytes = b"".join(chunks)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    if not raw_bytes or len(raw_bytes) > SIZE_CAP:
        raise ContractError(code="not_configured", message="proxy key unavailable")
    try:
        raw = raw_bytes.strip().decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError(code="not_configured", message="proxy key unavailable") from exc
    if TOKEN_RE.fullmatch(raw) is None:
        raise ContractError(code="not_configured", message="proxy key unavailable")
    return raw


def generate_proxy_key(path: Path) -> str:
    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(target), flags, 0o600)
    except FileExistsError as exc:
        raise ContractError(code="already_exists", message="proxy key exists") from exc
    except OSError as exc:
        raise ContractError(code="not_configured", message="proxy key unavailable") from exc
    try:
        os.write(fd, (token + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chmod(str(target), 0o600)
    except OSError:
        pass
    return token


def check_proxy_key(provided: str | None, expected: str) -> bool:
    if not isinstance(provided, str) or not provided:
        return False
    try:
        return hmac.compare_digest(provided.strip(), expected)
    except (TypeError, ValueError):
        return False


def check_origin_exact(provided: str | None, expected: str) -> bool:
    if not isinstance(provided, str) or not provided:
        return False
    try:
        return hmac.compare_digest(provided.strip(), expected)
    except (TypeError, ValueError):
        return False


def check_csrf(provided: str | None, expected: str) -> bool:
    if not isinstance(provided, str) or not provided or not expected:
        return False
    try:
        return hmac.compare_digest(provided.strip(), expected)
    except (TypeError, ValueError):
        return False


def extract_session_cookie(cookie_header: str | None, name: str) -> str | None:
    if cookie_header is None:
        return None
    if not isinstance(cookie_header, str) or not cookie_header or len(cookie_header) > 8192:
        raise ContractError(code="bad_payload", message="cookie invalid")
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception as exc:
        raise ContractError(code="bad_payload", message="cookie invalid") from exc
    matches = [m for k, m in jar.items() if k == name]
    if not matches:
        return None
    if len(matches) != 1:
        raise ContractError(code="bad_payload", message="cookie invalid")
    value = matches[0].value.strip()
    if not value:
        return None
    if SESSION_COOKIE_RE.fullmatch(value) is None:
        raise ContractError(code="bad_payload", message="cookie invalid")
    return value


def set_cookie_header(name: str, value: str, secure: bool) -> str:
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header(name: str, secure: bool) -> str:
    parts = [
        f"{name}=deleted",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def safe_b64_note(value: str) -> str:
    try:
        base64.b64decode(value.encode("ascii"))
        return "present"
    except (ValueError, TypeError):
        return "present"
