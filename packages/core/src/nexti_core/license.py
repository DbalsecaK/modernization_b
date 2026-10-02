"""Offline license (spec 14.4, ADR-0030): a JSON file signed with Ed25519 by NexTI, with a detached signature.

The signature covers the exact bytes of the license file and is stored next to it (`license.json.sig`, base64). The
platform verifies it with the public key it is configured with; it never holds the private key. A license that is
configured but missing, invalid, expired or exceeded leaves the platform read-only (the API decides what that blocks).

NexTI's command line (the private key never leaves NexTI):

    python -m nexti_core.license keygen --out nexti-license
    python -m nexti_core.license sign --key nexti-license.key --customer "Andes Bank" --profile air-gapped \
        --expires 2027-12-31 --max-tenants 2 --max-projects 20 --feature modernization --out license.json
    python -m nexti_core.license verify --public-key nexti-license.pub --license license.json
"""

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from nexti_core import signing

FORMAT: Literal[1] = 1
SIGNATURE_SUFFIX = ".sig"

LicenseState = Literal["not_required", "valid", "missing", "invalid", "expired", "over_limits"]
# Stable reasons, safe to show and to branch on.
LicenseReason = Literal[
    "public_key_missing", "public_key_invalid", "file_not_found", "signature_not_found", "bad_signature", "malformed",
    "not_yet_valid", "expired", "max_tenants", "max_projects",
]  # fmt: skip


class License(BaseModel):
    """What NexTI signs. Unknown fields are refused so that a license is read the same way everywhere."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal[1] = FORMAT
    license_id: str
    customer: str = Field(min_length=1)
    deployment_profile: str = Field(min_length=1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    max_tenants: int = Field(ge=1)
    max_projects: int = Field(ge=1)
    features: list[str] = Field(default_factory=list)

    def to_bytes(self) -> bytes:
        return (json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()


@dataclass(frozen=True)
class LicenseCheck:
    """The result of reading and verifying the file (once, at startup); expiry and limits are evaluated later."""

    configured: bool
    license: License | None = None
    reason: LicenseReason | None = None

    @property
    def verified(self) -> bool:
        return self.license is not None


@dataclass(frozen=True)
class Usage:
    tenants: int
    projects: int


@dataclass(frozen=True)
class LicenseStatus:
    state: LicenseState
    license: License | None
    reason: LicenseReason | None
    usage: Usage | None

    @property
    def read_only(self) -> bool:
        return self.state not in ("not_required", "valid")


def signature_path(license_file: Path) -> Path:
    return license_file.with_name(license_file.name + SIGNATURE_SUFFIX)


def check_license(license_file: str, public_key: str, signature_file: str = "") -> LicenseCheck:
    """Read and verify the configured license. No `license_file` means a license is not required (SaaS, dev)."""
    if not license_file:
        return LicenseCheck(configured=False)
    if not public_key:
        return LicenseCheck(configured=True, reason="public_key_missing")
    try:
        key = signing.load_public(public_key)
    except signing.SigningKeyError:
        return LicenseCheck(configured=True, reason="public_key_invalid")
    path = Path(license_file)
    sig_path = Path(signature_file) if signature_file else signature_path(path)
    if not path.is_file():
        return LicenseCheck(configured=True, reason="file_not_found")
    if not sig_path.is_file():
        return LicenseCheck(configured=True, reason="signature_not_found")
    data = path.read_bytes()
    if not signing.verify(key, data, sig_path.read_text(encoding="ascii", errors="replace")):
        return LicenseCheck(configured=True, reason="bad_signature")
    try:
        return LicenseCheck(configured=True, license=License.model_validate_json(data))
    except ValidationError:
        return LicenseCheck(configured=True, reason="malformed")


def evaluate(check: LicenseCheck, now: datetime, usage: Usage | None) -> LicenseStatus:
    """The state at `now` with the current usage (None when it could not be counted: limits are not judged)."""
    if not check.configured:
        return LicenseStatus("not_required", None, None, None)
    lic = check.license
    if lic is None:
        state: LicenseState = "missing" if check.reason in ("file_not_found", "signature_not_found") else "invalid"
        return LicenseStatus(state, None, check.reason, usage)
    if now < lic.issued_at:
        return LicenseStatus("invalid", lic, "not_yet_valid", usage)
    if now >= lic.expires_at:
        return LicenseStatus("expired", lic, "expired", usage)
    if usage is not None and usage.tenants > lic.max_tenants:
        return LicenseStatus("over_limits", lic, "max_tenants", usage)
    if usage is not None and usage.projects > lic.max_projects:
        return LicenseStatus("over_limits", lic, "max_projects", usage)
    return LicenseStatus("valid", lic, None, usage)


def issue(
    key: Ed25519PrivateKey,
    *,
    customer: str,
    deployment_profile: str,
    expires_at: datetime,
    max_tenants: int,
    max_projects: int,
    features: Sequence[str] = (),
    issued_at: datetime | None = None,
) -> tuple[bytes, str]:
    """A license file's bytes and their detached signature (base64)."""
    lic = License(
        license_id=str(uuid.uuid4()), customer=customer, deployment_profile=deployment_profile,
        issued_at=issued_at or datetime.now(UTC).replace(microsecond=0), expires_at=expires_at,
        max_tenants=max_tenants, max_projects=max_projects, features=sorted(set(features)),
    )  # fmt: skip
    data = lic.to_bytes()
    return data, signing.sign(key, data)


def _passphrase(env: str | None) -> bytes | None:
    if not env:
        return None
    value = os.environ.get(env)
    if not value:
        raise SystemExit(f"the environment variable {env} is empty")
    return value.encode()


def _expiry(value: str) -> datetime:
    """A date (end of that day, UTC) or an ISO date-time with its offset."""
    if len(value) == 10:
        return datetime.combine(datetime.fromisoformat(value).date(), time(23, 59, 59), tzinfo=UTC)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("give the offset, e.g. 2027-12-31T23:59:59Z")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexti_core.license", description="NexTI offline licenses.")
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen", help="create the signing key pair (<out>.key private, <out>.pub public)")
    keygen.add_argument("--out", required=True, help="path prefix of the two files")
    keygen.add_argument("--passphrase-env", help="environment variable with a passphrase to encrypt the private key")
    sign = commands.add_parser("sign", help="issue a license file and its detached signature (<out>.sig)")
    sign.add_argument("--key", required=True, type=Path)
    sign.add_argument("--passphrase-env")
    sign.add_argument("--customer", required=True)
    sign.add_argument("--profile", required=True, help="deployment profile, e.g. air-gapped or on-prem")
    sign.add_argument("--expires", required=True, type=_expiry, help="YYYY-MM-DD (end of day, UTC) or ISO date-time")
    sign.add_argument("--max-tenants", required=True, type=int)
    sign.add_argument("--max-projects", required=True, type=int)
    sign.add_argument("--feature", action="append", default=[], help="an enabled feature (repeatable)")
    sign.add_argument("--out", required=True, type=Path)
    verify = commands.add_parser("verify", help="verify a license and print its state")
    verify.add_argument("--public-key", required=True, help="PEM file, PEM text or base64 of the raw key")
    verify.add_argument("--license", required=True, type=Path)
    verify.add_argument("--signature", type=Path, help=f"default: <license>{SIGNATURE_SUFFIX}")
    args = parser.parse_args(argv)

    if args.command == "keygen":
        private, public = Path(args.out + ".key"), Path(args.out + ".pub")
        raw = signing.generate(private, public, _passphrase(args.passphrase_env))
        print(f"private key: {private} (keep it offline; never commit it)")
        print(f"public key:  {public}")
        print(f"public key for LICENSE_PUBLIC_KEY: {raw}")
        return 0
    if args.command == "sign":
        key = signing.load_private(args.key, _passphrase(args.passphrase_env))
        data, signature = issue(
            key, customer=args.customer, deployment_profile=args.profile, expires_at=args.expires,
            max_tenants=args.max_tenants, max_projects=args.max_projects, features=args.feature,
        )  # fmt: skip
        args.out.write_bytes(data)
        signature_path(args.out).write_text(signature + "\n", encoding="ascii")
        print(f"license: {args.out}\nsignature: {signature_path(args.out)}")
        return 0
    public_key = signing.load_public_file_or_value(args.public_key)
    check = check_license(str(args.license), signing.raw_public(public_key), str(args.signature or ""))
    status = evaluate(check, datetime.now(UTC), None)
    out: dict[str, Any] = {"state": status.state, "reason": status.reason}
    if status.license is not None:
        out["license"] = status.license.model_dump(mode="json")
    print(json.dumps(out, indent=2))
    return 0 if status.state == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
