"""Offline license (ADR-0030): a valid license enables; expired, tampered, foreign-key or exceeded ones do not."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexti_core import license as lic
from nexti_core import signing

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def write(tmp_path: Path, key: Ed25519PrivateKey, *, expires: datetime = NOW + timedelta(days=30)) -> Path:
    data, signature = lic.issue(
        key, customer="Andes Bank", deployment_profile="air-gapped", expires_at=expires, max_tenants=2,
        max_projects=3, features=["modernization"], issued_at=NOW - timedelta(days=1),
    )  # fmt: skip
    path = tmp_path / "license.json"
    path.write_bytes(data)
    lic.signature_path(path).write_text(signature)
    return path


def public(key: Ed25519PrivateKey) -> str:
    return signing.raw_public(key.public_key())


def test_valid_expired_tampered_foreign_and_over_limits(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    path = write(tmp_path, key)
    check = lic.check_license(str(path), public(key))
    status = lic.evaluate(check, NOW, lic.Usage(tenants=2, projects=3))
    assert (status.state, status.read_only) == ("valid", False)
    assert status.license is not None
    assert status.license.customer == "Andes Bank"

    assert lic.evaluate(check, NOW + timedelta(days=31), None).state == "expired"
    over = lic.evaluate(check, NOW, lic.Usage(tenants=1, projects=4))
    assert (over.state, over.reason, over.read_only) == ("over_limits", "max_projects", True)
    assert lic.evaluate(check, NOW, lic.Usage(tenants=3, projects=0)).reason == "max_tenants"

    foreign = lic.check_license(str(path), public(Ed25519PrivateKey.generate()))
    assert (foreign.reason, lic.evaluate(foreign, NOW, None).state) == ("bad_signature", "invalid")

    body = json.loads(path.read_text())
    body["max_projects"] = 1000
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    assert lic.check_license(str(path), public(key)).reason == "bad_signature"


def test_missing_and_misconfigured(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    absent = lic.check_license(str(tmp_path / "nope.json"), public(key))
    assert (absent.reason, lic.evaluate(absent, NOW, None).state) == ("file_not_found", "missing")
    path = write(tmp_path, key)
    lic.signature_path(path).unlink()
    assert lic.evaluate(lic.check_license(str(path), public(key)), NOW, None).state == "missing"
    assert lic.check_license(str(path), "").reason == "public_key_missing"
    assert lic.check_license(str(path), "not-a-key").reason == "public_key_invalid"


def test_not_configured_is_not_required() -> None:
    status = lic.evaluate(lic.check_license("", ""), NOW, None)
    assert (status.state, status.read_only) == ("not_required", False)


def test_signed_payload_with_unknown_fields_is_malformed(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    data = json.dumps({"customer": "x", "unlimited": True}).encode()
    path = tmp_path / "license.json"
    path.write_bytes(data)
    lic.signature_path(path).write_text(signing.sign(key, data))
    assert lic.check_license(str(path), public(key)).reason == "malformed"


def test_command_line_keygen_sign_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prefix = str(tmp_path / "nexti")
    assert lic.main(["keygen", "--out", prefix]) == 0
    out = tmp_path / "license.json"
    assert lic.main([
        "sign", "--key", prefix + ".key", "--customer", "Andes Bank", "--profile", "air-gapped",
        "--expires", "2099-12-31", "--max-tenants", "1", "--max-projects", "5", "--feature", "modernization",
        "--out", str(out),
    ]) == 0  # fmt: skip
    capsys.readouterr()
    assert lic.main(["verify", "--public-key", prefix + ".pub", "--license", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "valid"
    other = str(tmp_path / "other")
    lic.main(["keygen", "--out", other])
    capsys.readouterr()
    assert lic.main(["verify", "--public-key", other + ".pub", "--license", str(out)]) == 1
    assert "PRIVATE" not in capsys.readouterr().out
