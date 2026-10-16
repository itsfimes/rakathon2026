from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from rakathon_backend.b2.iris.config import (
    IrisFhirConfig,
    IrisSqlConfig,
    VectorStoreConfig,
    vector_sql_configs,
)
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.screening_sql import ScreeningSqlStore
from rakathon_backend.b2.iris.sql import IrisSqlStore
from rakathon_backend.b2.iris.storage import CompositeIrisStorage
from rakathon_backend.b2.iris.task_sql import make_factory
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.bridge.client import BridgeClientConfig, EncryptedBridgeStorage
from rakathon_backend.bridge.server import build_server, serve_forever
from rakathon_backend.common.errors import ContractError


def bridge_store_from_env() -> EncryptedBridgeStorage:
    insecure = os.environ.get("RAKATHON_BRIDGE_INSECURE_LOOPBACK", "0").strip() == "1"
    config = BridgeClientConfig.from_env(dict(os.environ), allow_insecure_loopback=insecure)
    return EncryptedBridgeStorage(config)


def cmd_bridge_serve(bind: str, port: int, mock_storage: bool) -> int:
    env = dict(os.environ)
    key_file = env.get("RAKATHON_BRIDGE_KEY_FILE", "").strip()
    key_id = env.get("RAKATHON_BRIDGE_KEY_ID", "").strip()
    if not key_file or not key_id:
        print(json.dumps({"error": "bridge key is not configured"}))
        return 2
    if mock_storage:
        store: Any = MemoryStorage()
        mode = "mock"
        screening: Any | None = None
    else:
        try:
            fhir_config = IrisFhirConfig.from_env(env)
        except ContractError as exc:
            print(json.dumps({"error": "iris_not_configured", "message": str(exc)}))
            return 2
        fhir = DirectFhirAdapter(fhir_config)
        try:
            sql_config = IrisSqlConfig.from_env(env)
        except ContractError:
            print(json.dumps({"error": "iris sql is not configured"}))
            return 2
        anon_cfg = VectorStoreConfig.anon_from_env(env)
        patient_cfg = VectorStoreConfig.patient_from_env(env)
        try:
            anon_sql, patient_sql = vector_sql_configs(env, sql_config)
        except ContractError as exc:
            print(json.dumps({"error": "vector sql is not configured", "message": str(exc)}))
            return 2
        anon_factory = make_factory(anon_sql) if anon_sql is not None else None
        patient_factory = make_factory(patient_sql) if patient_sql is not None else None
        if anon_cfg.enabled and anon_factory is None:
            print(json.dumps({"error": "vector anon enabled without sql credentials"}))
            return 2
        if patient_cfg.enabled and patient_factory is None:
            print(json.dumps({"error": "vector patient enabled without sql credentials"}))
            return 2
        sql = IrisSqlStore(
            sql_config,
            anon_factory=anon_factory,
            patient_factory=patient_factory,
            anon=anon_cfg,
            patient=patient_cfg,
        )
        tasks_factory = make_factory(sql_config)
        screening = ScreeningSqlStore(sql_config, factory=tasks_factory)
        store = CompositeIrisStorage(fhir, sql, screening=screening)
        mode = "bridge"
    server = build_server(
        bind, port, Path(key_file), key_id, store, mode=mode, screening=screening
    )
    print(json.dumps({"serving": True, "bind": bind, "port": port, "mode": mode}))
    sys.stdout.flush()
    serve_forever(server)
    return 0


def cmd_init_db() -> int:
    env = dict(os.environ)
    try:
        sql_config = IrisSqlConfig.from_env(env)
    except ContractError as exc:
        print(json.dumps({"error": "iris sql is not configured", "message": str(exc)}))
        return 2
    store = IrisSqlStore(sql_config)
    try:
        result = store.init_db()
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    print(json.dumps(result))
    return 0
