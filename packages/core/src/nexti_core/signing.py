"""Ed25519 keys and detached signatures: the root of trust of the offline license and the update bundles (ADR-0030).

NexTI keeps the private key outside the platform; the platform only ever holds the public key. A public key is given
as PEM (SubjectPublicKeyInfo) or as the base64 of its 32 raw bytes. A signature is stored as base64 text.
"""

import base64
import binascii
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class SigningKeyError(ValueError):
    """A key that cannot be read or is not an Ed25519 key."""


def generate(private_path: Path, public_path: Path, passphrase: bytes | None = None) -> str:
    """Write a new key pair (private PEM readable only by its owner, public PEM) and return the raw public key."""
    key = Ed25519PrivateKey.generate()
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
    )
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(pem)
    public = key.public_key()
    public_path.write_bytes(
        public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return raw_public(public)


def raw_public(key: Ed25519PublicKey) -> str:
    """The base64 of the 32 raw bytes: the form that fits in an environment variable."""
    return base64.b64encode(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def load_private(path: Path, passphrase: bytes | None = None) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=passphrase)
    except (ValueError, TypeError) as exc:
        raise SigningKeyError("the private key cannot be read") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("the private key is not an Ed25519 key")
    return key


def load_public(value: str) -> Ed25519PublicKey:
    """A public key from PEM text or from the base64 of its raw bytes."""
    text = value.strip()
    try:
        if text.startswith("-----BEGIN"):
            key = serialization.load_pem_public_key(text.encode())
            if not isinstance(key, Ed25519PublicKey):
                raise SigningKeyError("the public key is not an Ed25519 key")
            return key
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(text, validate=True))
    except (ValueError, binascii.Error) as exc:
        raise SigningKeyError("the public key cannot be read") from exc


def load_public_file_or_value(value: str) -> Ed25519PublicKey:
    """CLI convenience: a path to a PEM file, or the key itself."""
    path = Path(value)
    if len(value) < 512 and path.is_file():
        return load_public(path.read_text(encoding="utf-8"))
    return load_public(value)


def sign(key: Ed25519PrivateKey, data: bytes) -> str:
    return base64.b64encode(key.sign(data)).decode()


def verify(key: Ed25519PublicKey, data: bytes, signature: str) -> bool:
    """True only if `signature` (base64) is a signature of exactly `data` by `key`."""
    try:
        key.verify(base64.b64decode(signature.strip(), validate=True), data)
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True
