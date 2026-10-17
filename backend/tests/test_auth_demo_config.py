from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rakathon_backend.common.errors import ContractError
from rakathon_backend.web.demo_login import (
    DEMO_ACCOUNT_IDS,
    EXPECTED_ROLES,
    DemoLoginConfig,
    anon_session_body,
    auth_success_body,
    demo_account_from,
    demo_matches,
    load_demo_login_file,
    revoke_quietly,
)

USERNAMES = {
    "koordinator": "demo.koordinator",
    "lekar": "demo.lekar",
    "mdt": "demo.mdt",
    "pacient": "demo.pacient",
}
PASSWORDS = {
    "koordinator": "koordinator-pw-correct-horse-01",
    "lekar": "lekar-pw-correct-horse-02",
    "mdt": "mdt-pw-correct-horse-03",
    "pacient": "pacient-pw-correct-horse-04",
}


def write_demo_file(tmp_path: Path, payload: object, mode: int = 0o600) -> Path:
    sec = tmp_path / "sec"
    sec.mkdir(exist_ok=True)
    os.chmod(sec, 0o700)
    target = sec / "demo-login.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(target, mode)
    return target


def valid_payload() -> dict[str, object]:
    return {
        account: {"username": USERNAMES[account], "password": PASSWORDS[account]}
        for account in DEMO_ACCOUNT_IDS
    }


def test_valid_file_loads_with_expected_roles(tmp_path: Path) -> None:
    config = load_demo_login_file(write_demo_file(tmp_path, valid_payload()))
    assert isinstance(config, DemoLoginConfig)
    assert EXPECTED_ROLES == {
        "koordinator": "coordinator",
        "lekar": "clinician",
        "mdt": "clinician",
        "pacient": "viewer",
    }
    for account in DEMO_ACCOUNT_IDS:
        creds = config.credentials_for(account)
        assert creds is not None
        assert creds[0] == USERNAMES[account]
        assert creds[1] == PASSWORDS[account]
        expected = config.expected_for(account)
        assert expected == (USERNAMES[account], EXPECTED_ROLES[account])
    assert config.credentials_for("unknown") is None
    assert config.expected_for("unknown") is None


def test_view_derived_from_username_and_role(tmp_path: Path) -> None:
    config = load_demo_login_file(write_demo_file(tmp_path, valid_payload()))
    assert config.view_for("demo.lekar", "clinician") == "lekar"
    assert config.view_for("demo.lekar", "viewer") is None
    assert config.view_for("demo.pacient", "clinician") is None
    assert config.view_for("nobody.nobody", "viewer") is None


def test_repr_and_errors_carry_no_secrets(tmp_path: Path) -> None:
    config = load_demo_login_file(write_demo_file(tmp_path, valid_payload()))
    assert PASSWORDS["koordinator"] not in repr(config)
    assert USERNAMES["koordinator"] not in repr(config)
    bad = valid_payload()
    bad["koordinator"] = {"username": "badnodot", "password": PASSWORDS["koordinator"]}
    with pytest.raises(ContractError) as exc_info:
        load_demo_login_file(write_demo_file(tmp_path, bad))
    assert exc_info.value.code == "not_configured"
    assert PASSWORDS["koordinator"] not in str(exc_info.value)
    assert "badnodot" not in str(exc_info.value)


def test_key_set_must_match_exactly(tmp_path: Path) -> None:
    missing = valid_payload()
    del missing["mdt"]
    with pytest.raises(ContractError):
        load_demo_login_file(write_demo_file(tmp_path, missing))
    extra = valid_payload()
    extra["admin"] = {"username": "extra.admin", "password": "extra-pw-correct-horse-05"}
    with pytest.raises(ContractError):
        load_demo_login_file(write_demo_file(tmp_path, extra))
    renamed = valid_payload()
    renamed["admin"] = renamed.pop("mdt")
    with pytest.raises(ContractError):
        load_demo_login_file(write_demo_file(tmp_path, renamed))


def test_entry_shape_is_closed(tmp_path: Path) -> None:
    cases = [
        {"username": USERNAMES["koordinator"]},
        {"password": PASSWORDS["koordinator"]},
        {
            "username": USERNAMES["koordinator"],
            "password": PASSWORDS["koordinator"],
            "role": "admin",
        },
        "not-a-dict",
        {"username": 123, "password": PASSWORDS["koordinator"]},
        {"username": "", "password": PASSWORDS["koordinator"]},
        {"username": USERNAMES["koordinator"], "password": ""},
        {"username": USERNAMES["koordinator"], "password": "x" * 257},
        {"username": "x" * 129, "password": PASSWORDS["koordinator"]},
        {"username": "badnodot", "password": PASSWORDS["koordinator"]},
    ]
    for bad_entry in cases:
        payload = valid_payload()
        payload["koordinator"] = bad_entry
        with pytest.raises(ContractError):
            load_demo_login_file(write_demo_file(tmp_path, payload))


def test_duplicate_normalized_usernames_rejected(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["lekar"] = {"username": "Demo.Koordinator", "password": PASSWORDS["lekar"]}
    with pytest.raises(ContractError):
        load_demo_login_file(write_demo_file(tmp_path, payload))


def test_not_a_dict_rejected(tmp_path: Path) -> None:
    with pytest.raises(ContractError):
        load_demo_login_file(write_demo_file(tmp_path, ["koordinator"]))
    target = write_demo_file(tmp_path, valid_payload())
    target.write_text("not json{{", encoding="utf-8")
    with pytest.raises(ContractError):
        load_demo_login_file(target)
    target.write_bytes(b"")
    with pytest.raises(ContractError):
        load_demo_login_file(target)
    target.write_bytes(b"x" * 9000)
    with pytest.raises(ContractError):
        load_demo_login_file(target)


def test_symlink_mode_parent_and_missing_rejected(tmp_path: Path) -> None:
    sec = tmp_path / "sec2"
    sec.mkdir(exist_ok=True)
    os.chmod(sec, 0o700)
    real = sec / "real.json"
    real.write_text(json.dumps(valid_payload()), encoding="utf-8")
    os.chmod(real, 0o600)
    link = sec / "link.json"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(real)
    with pytest.raises(ContractError):
        load_demo_login_file(link)
    loose = write_demo_file(tmp_path, valid_payload(), mode=0o644)
    with pytest.raises(ContractError):
        load_demo_login_file(loose)
    with pytest.raises(ContractError):
        load_demo_login_file(sec / "missing.json")
    with pytest.raises(ContractError):
        load_demo_login_file(sec)
    wide = tmp_path / "wide"
    wide.mkdir(exist_ok=True)
    os.chmod(wide, 0o755)
    wide_file = wide / "demo-login.json"
    wide_file.write_text(json.dumps(valid_payload()), encoding="utf-8")
    os.chmod(wide_file, 0o600)
    with pytest.raises(ContractError):
        load_demo_login_file(wide_file)


def test_response_helpers() -> None:
    assert anon_session_body(None) == {"authenticated": False}
    assert anon_session_body(DemoLoginConfig({}, {})) == {
        "authenticated": False,
        "demoAccounts": ["koordinator", "lekar", "mdt", "pacient"],
    }
    assert demo_account_from({"account": "lekar"}) == "lekar"
    assert demo_account_from({"account": "unknown"}) is None
    assert demo_account_from({"account": 1}) is None
    assert demo_account_from({"account": "lekar", "extra": 1}) is None
    config = DemoLoginConfig(dict(USERNAMES), dict(PASSWORDS))
    assert demo_matches(config, "mdt", "demo.mdt", "clinician") is True
    assert demo_matches(config, "mdt", "demo.mdt", "viewer") is False
    assert demo_matches(config, "mdt", "demo.lekar", "clinician") is False
    assert demo_matches(config, "nope", "demo.mdt", "clinician") is False
    seen: list[str] = []

    def ok(token: str) -> None:
        seen.append(token)

    revoke_quietly(ok, "tok")
    assert seen == ["tok"]

    def boom(token: str) -> None:
        _ = token
        raise RuntimeError("down")

    revoke_quietly(boom, "tok")
    body = auth_success_body("uid", "demo.mdt", "clinician", "csrf", config)
    assert body["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
    assert body["demoView"] == "mdt"
    plain = auth_success_body("uid", "demo.mdt", "clinician", "csrf", None)
    assert "demoAccounts" not in plain
    assert "demoView" not in plain
    other = auth_success_body("uid", "somebody.else", "viewer", "csrf", config)
    assert other["demoAccounts"] == ["koordinator", "lekar", "mdt", "pacient"]
    assert "demoView" not in other
