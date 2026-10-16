from __future__ import annotations

import ipaddress
import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from rakathon_backend.common.errors import ContractError

FORBIDDEN_SQL_PORTS = frozenset({443, 32783})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
TRUSTED_REMOTE_BASE = "https://iris.racek.xyz/fhir/r4"
IRIS_FHIR_BASE_URL_KEY = "RAKATHON_IRIS_FHIR_BASE_URL"
IRIS_FHIR_USER_KEY = "RAKATHON_IRIS_FHIR_USER"
IRIS_FHIR_PASSWORD_KEY = "RAKATHON_IRIS_FHIR_PASSWORD"
IRIS_FHIR_VERIFY_TLS_KEY = "RAKATHON_IRIS_FHIR_VERIFY_TLS"
IRIS_FHIR_ALLOW_DIRECT_KEY = "RAKATHON_IRIS_FHIR_ALLOW_DIRECT"


def _is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


def _check_sql_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool):
        raise ContractError(code="not_configured", message="iris sql port invalid")
    if port < 1 or port > 65535:
        raise ContractError(code="not_configured", message="iris sql port invalid")
    if port in FORBIDDEN_SQL_PORTS:
        raise ContractError(code="not_configured", message="use superserver port")
    return port


def _parse_port(raw: str) -> int:
    try:
        return _check_sql_port(int(raw.strip()))
    except ValueError as exc:
        raise ContractError(code="not_configured", message="iris sql port invalid") from exc


def _fhir_loopback_ok(base: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(base)
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    if parsed.fragment or parsed.username or parsed.password:
        return False
    host = parsed.hostname or ""
    if not _is_loopback_literal(host):
        return False
    return parsed.port is not None


@dataclass(frozen=True)
class IrisFhirConfig:
    base_url: str
    username: str
    password: str = field(repr=False)
    verify_tls: bool = True
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    trusted_remote: bool = False

    @staticmethod
    def _normalize_trusted_base(base: str) -> str | None:
        for ch in base:
            if ord(ch) < 33 or ord(ch) == 127:
                return None
        if "%" in base:
            return None
        text = base
        if text.endswith("/"):
            text = text[:-1]
            if text.endswith("/"):
                return None
        if text != TRUSTED_REMOTE_BASE:
            return None
        try:
            parsed = urllib.parse.urlparse(text)
        except ValueError:
            return None
        if parsed.scheme != "https":
            return None
        if parsed.hostname != "iris.racek.xyz":
            return None
        if parsed.port is not None:
            return None
        if parsed.path != "/fhir/r4":
            return None
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            return None
        return text

    @staticmethod
    def trusted_base() -> str:
        return TRUSTED_REMOTE_BASE

    @staticmethod
    def from_env(
        env: dict[str, str] | None = None,
        allow_insecure_loopback: bool = False,
        allow_direct_remote: bool = False,
    ) -> IrisFhirConfig:
        source = dict(os.environ) if env is None else dict(env)
        base = source.get(IRIS_FHIR_BASE_URL_KEY, "").strip()
        user = source.get(IRIS_FHIR_USER_KEY, "").strip()
        pw = source.get(IRIS_FHIR_PASSWORD_KEY, "").strip()
        if not base or not user or not pw:
            raise ContractError(code="not_configured", message="iris fhir is not configured")
        direct_ok = allow_direct_remote
        direct_ok = direct_ok and source.get(IRIS_FHIR_ALLOW_DIRECT_KEY, "").strip() == "1"
        normalized = IrisFhirConfig._normalize_trusted_base(base)
        if allow_direct_remote:
            if normalized is None:
                raise ContractError(code="not_configured", message="iris fhir needs https")
            if not direct_ok:
                raise ContractError(code="not_configured", message="fhir is loopback only")
            verify_raw = source.get(IRIS_FHIR_VERIFY_TLS_KEY, "1").strip()
            if verify_raw == "0":
                raise ContractError(code="not_configured", message="remote needs tls verify")
            return IrisFhirConfig(
                base_url=normalized,
                username=user,
                password=pw,
                verify_tls=True,
                trusted_remote=True,
            )
        if normalized is not None:
            raise ContractError(code="not_configured", message="fhir is loopback only")
        https_ok = base.startswith("https://")
        loopback_ok = allow_insecure_loopback and _fhir_loopback_ok(base)
        if not https_ok and not loopback_ok:
            raise ContractError(code="not_configured", message="iris fhir needs https")
        verify_raw = source.get(IRIS_FHIR_VERIFY_TLS_KEY, "1").strip()
        return IrisFhirConfig(
            base_url=base.rstrip("/"), username=user, password=pw, verify_tls=verify_raw != "0"
        )


@dataclass(frozen=True)
class IrisSqlConfig:
    host: str
    port: int
    namespace: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    schema: str = "FSB"

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> IrisSqlConfig:
        source = dict(os.environ) if env is None else dict(env)
        host = source.get("RAKATHON_IRIS_SQL_HOST", "").strip()
        port_raw = source.get("RAKATHON_IRIS_SQL_PORT", "").strip()
        ns = source.get("RAKATHON_IRIS_SQL_NAMESPACE", "").strip()
        user = source.get("RAKATHON_IRIS_SQL_USER", "").strip()
        pw = source.get("RAKATHON_IRIS_SQL_PASSWORD", "").strip()
        schema = source.get("RAKATHON_IRIS_SQL_SCHEMA", "FSB").strip() or "FSB"
        if not host or not port_raw or not ns or not user or not pw:
            raise ContractError(code="not_configured", message="iris sql is not configured")
        port = _parse_port(port_raw)
        if host not in LOOPBACK_HOSTS or not _is_loopback_literal(host):
            raise ContractError(code="not_configured", message="sql is loopback only")
        return IrisSqlConfig(
            host=host, port=port, namespace=ns, username=user, password=pw, schema=schema
        )


def vector_sql_config(
    prefix: str, base: IrisSqlConfig, env: dict[str, str]
) -> IrisSqlConfig | None:
    user_key = f"{prefix}_SQL_USER"
    pw_key = f"{prefix}_SQL_PASSWORD"
    user = env.get(user_key, "").strip()
    pw = env.get(pw_key, "").strip()
    if not user and not pw:
        return None
    if not user or not pw:
        raise ContractError(code="not_configured", message=f"{prefix} sql needs user+password")
    host = env.get(f"{prefix}_SQL_HOST", base.host).strip() or base.host
    port_raw = env.get(f"{prefix}_SQL_PORT", str(base.port)).strip() or str(base.port)
    ns = env.get(f"{prefix}_SQL_NAMESPACE", base.namespace).strip() or base.namespace
    port = _parse_port(port_raw)
    if host != base.host or port != base.port or ns != base.namespace:
        raise ContractError(code="not_configured", message=f"{prefix} must share superserver")
    if host not in LOOPBACK_HOSTS or not _is_loopback_literal(host):
        raise ContractError(code="not_configured", message="sql is loopback only")
    if user == base.username:
        raise ContractError(code="not_configured", message=f"{prefix} needs own username")
    return IrisSqlConfig(host=host, port=port, namespace=ns, username=user, password=pw)


def vector_sql_configs(
    env: dict[str, str], base: IrisSqlConfig
) -> tuple[IrisSqlConfig | None, IrisSqlConfig | None]:
    anon = vector_sql_config("RAKATHON_VECTOR_ANON", base, env)
    patient = vector_sql_config("RAKATHON_VECTOR_PATIENT", base, env)
    seen = {base.username}
    for cfg in (anon, patient):
        if cfg is None:
            continue
        if cfg.username in seen:
            raise ContractError(code="not_configured", message="vector users must differ")
        seen.add(cfg.username)
    return (anon, patient)


@dataclass(frozen=True)
class VectorStoreConfig:
    enabled: bool
    schema: str
    table: str
    dimensions: int
    synthetic_only: bool = True

    @staticmethod
    def anon_from_env(env: dict[str, str] | None = None) -> VectorStoreConfig:
        source = dict(os.environ) if env is None else dict(env)
        enabled = source.get("RAKATHON_VECTOR_ANON_ENABLED", "0").strip() == "1"
        schema = source.get("RAKATHON_VECTOR_ANON_SCHEMA", "").strip()
        table = source.get("RAKATHON_VECTOR_ANON_TABLE", "").strip()
        dims_raw = source.get("RAKATHON_VECTOR_ANON_DIMS", "0").strip() or "0"
        try:
            dims = int(dims_raw)
        except ValueError:
            dims = 0
        return VectorStoreConfig(
            enabled=enabled, schema=schema, table=table, dimensions=dims, synthetic_only=True
        )

    @staticmethod
    def patient_from_env(env: dict[str, str] | None = None) -> VectorStoreConfig:
        source = dict(os.environ) if env is None else dict(env)
        enabled = source.get("RAKATHON_VECTOR_PATIENT_ENABLED", "0").strip() == "1"
        schema = source.get("RAKATHON_VECTOR_PATIENT_SCHEMA", "").strip()
        table = source.get("RAKATHON_VECTOR_PATIENT_TABLE", "").strip()
        dims_raw = source.get("RAKATHON_VECTOR_PATIENT_DIMS", "0").strip() or "0"
        try:
            dims = int(dims_raw)
        except ValueError:
            dims = 0
        return VectorStoreConfig(
            enabled=enabled, schema=schema, table=table, dimensions=dims, synthetic_only=False
        )


def key_path_from_env(env: dict[str, str] | None = None) -> Path:
    source = dict(os.environ) if env is None else dict(env)
    raw = source.get("RAKATHON_BRIDGE_KEY_FILE", "").strip()
    if not raw:
        raise ContractError(code="not_configured", message="bridge key is not configured")
    return Path(raw)
