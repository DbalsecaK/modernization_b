"""Signed update bundle (ADR-0030): a changed file or a foreign signature is refused before anything is loaded."""

import io
import json
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexti_core import update_bundle as ub

CHART = Path(__file__).resolve().parents[3] / "infra" / "helm" / "nexti"


def tiny_bundle(tmp_path: Path, key: Ed25519PrivateKey) -> Path:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "api.tar").write_bytes(b"fake image layers")
    (src / "nexti-0.9.0.tgz").write_bytes(b"fake chart")
    (src / "api.spdx.json").write_text('{"spdxVersion": "SPDX-2.3"}')
    files = {"images/01-api.tar": src / "api.tar", "chart/nexti-0.9.0.tgz": src / "nexti-0.9.0.tgz",
             "sbom/api.spdx.json": src / "api.spdx.json"}  # fmt: skip
    image = ub.ImageEntry(ref="ghcr.io/dbalsecak/nexti-api:0.9.0", id="sha256:" + "a" * 64,
                          file="images/01-api.tar", kind="platform")  # fmt: skip
    out = tmp_path / "bundle.tar"
    ub.pack(out, files, key, version="0.9.0", images=[image], chart="chart/nexti-0.9.0.tgz")
    return out


def rewrite(bundle: Path, change: dict[str, bytes | None]) -> None:
    """Copy the bundle replacing (or dropping, with None) some members, keeping the original manifest."""
    with tarfile.open(bundle) as tar:
        members = [(m, tar.extractfile(m).read()) for m in tar]  # type: ignore[union-attr]
    with tarfile.open(bundle, "w") as tar:
        for member, data in members:
            if member.name in change:
                if change[member.name] is None:
                    continue
                data = change[member.name] or b""
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))


def test_valid_bundle_verifies_and_extracts(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    manifest = ub.verify(bundle, key.public_key())
    assert (manifest.version, sorted(manifest.files)) == (
        "0.9.0", ["chart/nexti-0.9.0.tgz", "images/01-api.tar", "sbom/api.spdx.json"])  # fmt: skip
    ub.extract(bundle, key.public_key(), tmp_path / "out")
    assert (tmp_path / "out" / "images" / "01-api.tar").read_bytes() == b"fake image layers"


def test_tampered_file_is_rejected(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    rewrite(bundle, {"images/01-api.tar": b"fake image layers + backdoor"})
    with pytest.raises(ub.BundleError, match="do not match"):
        ub.verify(bundle, key.public_key())


def test_missing_or_extra_file_is_rejected(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    rewrite(bundle, {"sbom/api.spdx.json": None})
    with pytest.raises(ub.BundleError, match="missing"):
        ub.verify(bundle, key.public_key())
    bundle = tiny_bundle(tmp_path, key)
    with tarfile.open(bundle, "a") as tar:
        info = tarfile.TarInfo("images/02-extra.tar")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"bad"))
    with pytest.raises(ub.BundleError, match="not in the manifest"):
        ub.verify(bundle, key.public_key())


def test_foreign_signature_and_edited_manifest_are_rejected(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    with pytest.raises(ub.BundleError, match="signature"):
        ub.verify(bundle, Ed25519PrivateKey.generate().public_key())
    with tarfile.open(bundle) as tar:
        manifest = json.loads(tar.extractfile(ub.MANIFEST).read())  # type: ignore[union-attr]
    manifest["images"][0]["ref"] = "evil.example/nexti-api:0.9.0"
    rewrite(bundle, {ub.MANIFEST: json.dumps(manifest).encode()})
    with pytest.raises(ub.BundleError, match="signature"):
        ub.verify(bundle, key.public_key())


def test_unsafe_member_is_rejected(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    with tarfile.open(bundle, "a") as tar:
        info = tarfile.TarInfo("../escape.sh")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ub.BundleError, match="unsafe path"):
        ub.verify(bundle, key.public_key())


def test_load_refuses_before_running_docker_and_loads_a_valid_bundle(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = tiny_bundle(tmp_path, key)
    calls: list[list[str]] = []

    def run(args: Sequence[str]) -> str:
        calls.append(list(args))
        return ""

    with pytest.raises(ub.BundleError):
        ub.load(bundle, Ed25519PrivateKey.generate().public_key(), run=run, workdir=tmp_path / "w1")
    assert calls == []
    ub.load(bundle, key.public_key(), registry="registry.local:5000", push=True, run=run, workdir=tmp_path / "w2",
            chart_dest=tmp_path / "charts")  # fmt: skip
    image_id = "sha256:" + "a" * 64
    assert calls[1:] == [
        ["docker", "tag", image_id, "ghcr.io/dbalsecak/nexti-api:0.9.0"],
        ["docker", "tag", image_id, "registry.local:5000/nexti-api:0.9.0"],
        ["docker", "push", "registry.local:5000/nexti-api:0.9.0"],
    ]
    assert calls[0][:3] == ["docker", "load", "--input"]
    assert (tmp_path / "charts" / "nexti-0.9.0.tgz").read_bytes() == b"fake chart"


def test_images_come_from_the_chart() -> None:
    images = ub.images_from_chart(CHART)
    assert {"nexti-api", "nexti-worker", "nexti-web", "nexti-migrate"} <= {
        ref.rsplit("/", 1)[-1].split(":")[0] for ref in images.platform
    }
    assert all(ref.endswith(":" + images.version) for ref in images.platform)
    assert any("dind-rootless" in ref for ref in images.sandbox)
    assert any(ref.endswith("/nexti-sandbox-java:2") for ref in images.sandbox)
    assert ub.registry_name(images.sandbox[0], "reg.local:5000").startswith("reg.local:5000/docker:")
