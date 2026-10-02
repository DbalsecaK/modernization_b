"""Signed update bundle for air-gapped installations (spec 14.3, ADR-0030).

A bundle is an uncompressed tar with:

- `images/*.tar`: the platform and sandbox images (`docker save`), the ones `infra/helm/nexti` deploys;
- `chart/*.tgz`: the Helm chart (`helm package`);
- `sbom/*`: the SBOMs, when given;
- `manifest.json`: the version, the images (reference, image id, file) and the SHA-256 and size of every file;
- `manifest.sig`: the Ed25519 signature of `manifest.json`, with the same root of trust as the license (keyless
  cosign needs the internet).

`verify` checks the signature and every hash without extracting anything; `load` verifies, extracts only the files the
manifest lists (hashing them again while it writes), and only then runs `docker load`, retags and optionally pushes
to the local registry. Nothing is loaded from a bundle that fails a single check.

This module never starts processes itself (only the sandbox does, in the platform): docker and helm are run by the
operator's command line, `scripts/airgap/bundle.py`, which passes its runner to `main`:

    python scripts/airgap/bundle.py build --key nexti-license.key --out nexti-0.9.0.tar [--sbom-dir sbom]
    python scripts/airgap/bundle.py verify --public-key nexti-license.pub nexti-0.9.0.tar
    python scripts/airgap/bundle.py load --public-key nexti-license.pub nexti-0.9.0.tar --registry reg.local:5000
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any, Literal

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexti_core import signing

MANIFEST = "manifest.json"
SIGNATURE = "manifest.sig"
CHUNK = 1024 * 1024
_IMAGE_HELPER = re.compile(r'include "nexti\.image" \(list \. "([a-z0-9][a-z0-9-]*)"\)')
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

Runner = Callable[[Sequence[str]], str]


class BundleError(Exception):
    """The bundle cannot be trusted or used; nothing was loaded."""


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class ImageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str  # as the chart references it, e.g. ghcr.io/dbalsecak/nexti-api:0.9.0
    id: str  # the image id (config digest), kept by docker save/load
    file: str
    kind: Literal["platform", "sandbox"]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal[1] = 1
    version: str
    created_at: datetime
    images: list[ImageEntry] = Field(default_factory=list)
    chart: str | None = None
    files: dict[str, FileEntry]


@dataclass(frozen=True)
class ChartImages:
    version: str
    platform: list[str]
    sandbox: list[str]


def images_from_chart(chart_dir: Path) -> ChartImages:
    """The images the chart deploys: its components, the sandbox daemon and the sandbox images (values.yaml)."""
    values = yaml.safe_load((chart_dir / "values.yaml").read_text(encoding="utf-8"))
    chart = yaml.safe_load((chart_dir / "Chart.yaml").read_text(encoding="utf-8"))
    registry = str(values["image"]["registry"]).rstrip("/")
    tag = str(values["image"].get("tag") or chart["appVersion"])
    components = sorted(
        {
            name
            for t in sorted((chart_dir / "templates").glob("*.yaml"))
            for name in _IMAGE_HELPER.findall(t.read_text())
        }
    )
    sandbox = values["worker"]["sandbox"]
    return ChartImages(
        version=str(chart["appVersion"]),
        platform=[f"{registry}/{name}:{tag}" for name in components],
        sandbox=[str(sandbox["image"]), *(f"{registry}/{name}" for name in sandbox.get("images", []))],
    )


def _sha256_file(path: Path) -> FileEntry:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        while chunk := src.read(CHUNK):
            digest.update(chunk)
    return FileEntry(sha256=digest.hexdigest(), size=path.stat().st_size)


def _check_name(name: str) -> str:
    """A bundle path: relative, POSIX, no `..`, no empty parts."""
    path = PurePosixPath(name)
    if not name or name.startswith("/") or "\\" in name or ":" in name or any(p in ("", ".", "..") for p in path.parts):
        raise BundleError(f"unsafe path in the bundle: {name!r}")
    return name


def pack(
    out: Path,
    files: dict[str, Path],
    key: Ed25519PrivateKey,
    *,
    version: str,
    images: Sequence[ImageEntry] = (),
    chart: str | None = None,
) -> Manifest:
    """Write a bundle with `files` (bundle path -> local file), its manifest and the manifest's signature."""
    for name in files:
        _check_name(name)
        if name in (MANIFEST, SIGNATURE):
            raise BundleError(f"reserved name: {name}")
    listed = {i.file for i in images} | ({chart} if chart else set())
    if not listed <= files.keys():
        raise BundleError(f"files not in the bundle: {sorted(listed - files.keys())}")
    manifest = Manifest(
        version=version, created_at=datetime.now(UTC).replace(microsecond=0), images=list(images), chart=chart,
        files={name: _sha256_file(path) for name, path in sorted(files.items())},
    )  # fmt: skip
    data = (manifest.model_dump_json(indent=2) + "\n").encode()
    signature = (signing.sign(key, data) + "\n").encode()
    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as tar:
        for name, content in ((MANIFEST, data), (SIGNATURE, signature)):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), 0o644, int(manifest.created_at.timestamp())
            tar.addfile(info, io.BytesIO(content))
        for name, path in sorted(files.items()):
            info = tar.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with path.open("rb") as src:
                tar.addfile(info, src)
    return manifest


def _members(tar: tarfile.TarFile) -> Iterator[tuple[tarfile.TarInfo, IO[bytes]]]:
    seen: set[str] = set()
    for member in tar:
        name = _check_name(member.name)
        if not member.isreg():
            raise BundleError(f"not a regular file: {name}")
        if name in seen:
            raise BundleError(f"duplicate entry: {name}")
        seen.add(name)
        src = tar.extractfile(member)
        if src is None:  # pragma: no cover - regular members always have a stream
            raise BundleError(f"unreadable entry: {name}")
        yield member, src


def _hash_stream(src: IO[bytes], sink: IO[bytes] | None = None) -> FileEntry:
    digest, size = hashlib.sha256(), 0
    while chunk := src.read(CHUNK):
        digest.update(chunk)
        size += len(chunk)
        if sink is not None:
            sink.write(chunk)
    return FileEntry(sha256=digest.hexdigest(), size=size)


def _trusted_manifest(data: bytes | None, signature: bytes | None, key: Ed25519PublicKey) -> Manifest:
    if data is None or signature is None:
        raise BundleError("the bundle has no manifest or no signature")
    if not signing.verify(key, data, signature.decode("ascii", errors="replace")):
        raise BundleError("the manifest signature is not valid for this key")
    try:
        return Manifest.model_validate_json(data)
    except ValidationError as exc:
        raise BundleError("the signed manifest is not valid") from exc


def verify(bundle: Path, key: Ed25519PublicKey) -> Manifest:
    """Check the signature and that the bundle holds exactly the manifest's files with their hashes."""
    data = signature = None
    found: dict[str, FileEntry] = {}
    try:
        with tarfile.open(bundle, "r:") as tar:
            for member, src in _members(tar):
                if member.name == MANIFEST:
                    data = src.read(CHUNK * 4)
                elif member.name == SIGNATURE:
                    signature = src.read(1024)
                else:
                    found[member.name] = _hash_stream(src)
    except tarfile.TarError as exc:
        raise BundleError("the bundle is not a readable tar") from exc
    manifest = _trusted_manifest(data, signature, key)
    if missing := sorted(manifest.files.keys() - found.keys()):
        raise BundleError(f"files missing from the bundle: {missing}")
    if extra := sorted(found.keys() - manifest.files.keys()):
        raise BundleError(f"files not in the manifest: {extra}")
    if changed := sorted(name for name, entry in manifest.files.items() if found[name] != entry):
        raise BundleError(f"files that do not match the manifest: {changed}")
    return manifest


def extract(bundle: Path, key: Ed25519PublicKey, dest: Path) -> Manifest:
    """Verify, then write the manifest's files under `dest`, checking each hash again as it is written."""
    manifest = verify(bundle, key)
    with tarfile.open(bundle, "r:") as tar:
        for member, src in _members(tar):
            expected = manifest.files.get(member.name)
            if expected is None:
                continue
            target = dest.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as sink:
                written = _hash_stream(src, sink)
            if written != expected:  # changed after verification
                target.unlink()
                raise BundleError(f"file changed while extracting: {member.name}")
    return manifest


def local_name(ref: str) -> str:
    """The reference without a digest (a tag can be applied to it)."""
    return ref.split("@", 1)[0]


def registry_name(ref: str, registry: str) -> str:
    """`ref` moved to `registry`: ghcr.io/x/nexti-api:1 -> reg.local:5000/nexti-api:1."""
    path = local_name(ref).rsplit("/", 1)[-1]
    return f"{registry.rstrip('/')}/{path}"


class CommandError(Exception):
    """A docker or helm command failed (raised by the runner)."""


def load(
    bundle: Path,
    key: Ed25519PublicKey,
    *,
    registry: str | None = None,
    push: bool = False,
    docker: str = "docker",
    run: Runner,
    chart_dest: Path | None = None,
    workdir: Path | None = None,
) -> Manifest:
    """Verify and extract the bundle, then `docker load` each image, tag it and optionally push it to `registry`.
    The chart is copied to `chart_dest` for `helm upgrade`."""
    with _scratch(workdir) as tmp:
        manifest = extract(bundle, key, tmp)
        for image in manifest.images:
            run([docker, "load", "--input", str(tmp.joinpath(*PurePosixPath(image.file).parts))])
            run([docker, "tag", image.id, local_name(image.ref)])
            if registry:
                target = registry_name(image.ref, registry)
                run([docker, "tag", image.id, target])
                if push:
                    run([docker, "push", target])
        if manifest.chart and chart_dest is not None:
            chart_dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                tmp.joinpath(*PurePosixPath(manifest.chart).parts), chart_dest / PurePosixPath(manifest.chart).name
            )
    return manifest


@contextmanager
def _scratch(workdir: Path | None) -> Iterator[Path]:
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        yield workdir
        return
    with tempfile.TemporaryDirectory(prefix="nexti-bundle-") as tmp:
        yield Path(tmp)


def build(
    out: Path,
    key: Ed25519PrivateKey,
    chart_dir: Path,
    *,
    sbom_dir: Path | None = None,
    docker: str = "docker",
    helm: str = "helm",
    run: Runner,
) -> Manifest:
    """Save the chart's images, package the chart, add the SBOMs and write the signed bundle."""
    wanted = images_from_chart(chart_dir)
    with tempfile.TemporaryDirectory(prefix="nexti-bundle-") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "images").mkdir()
        (tmp / "chart").mkdir()
        files: dict[str, Path] = {}
        images: list[ImageEntry] = []
        refs: list[tuple[str, Literal["platform", "sandbox"]]] = [(r, "platform") for r in wanted.platform]
        refs += [(r, "sandbox") for r in wanted.sandbox]
        for n, (ref, kind) in enumerate(refs, start=1):
            name = f"images/{n:02d}-{_SAFE.sub('_', local_name(ref).rsplit('/', 1)[-1])}.tar"
            image_id = run([docker, "image", "inspect", "--format", "{{.Id}}", ref]).strip()
            run([docker, "save", "--output", str(tmp / name), ref])
            files[name] = tmp / name
            images.append(ImageEntry(ref=ref, id=image_id, file=name, kind=kind))
        run([helm, "package", str(chart_dir), "--destination", str(tmp / "chart")])
        packaged = sorted((tmp / "chart").glob("*.tgz"))
        if len(packaged) != 1:
            raise BundleError("helm package did not produce one chart")
        chart = f"chart/{packaged[0].name}"
        files[chart] = packaged[0]
        if sbom_dir is not None:
            for sbom in sorted(p for p in sbom_dir.iterdir() if p.is_file()):
                files[f"sbom/{sbom.name}"] = sbom
        return pack(out, files, key, version=wanted.version, images=images, chart=chart)


def _passphrase(env: str | None) -> bytes | None:
    if not env:
        return None
    value = os.environ.get(env)
    if not value:
        raise SystemExit(f"the environment variable {env} is empty")
    return value.encode()


def _summary(manifest: Manifest) -> dict[str, Any]:
    return {
        "version": manifest.version,
        "created_at": manifest.created_at.isoformat(),
        "images": [i.ref for i in manifest.images],
        "chart": manifest.chart,
        "files": len(manifest.files),
    }


def main(run: Runner, argv: Sequence[str] | None = None) -> int:
    """The operator's command line; `run` executes docker and helm (see scripts/airgap/bundle.py)."""
    repo_chart = Path(__file__).resolve().parents[4] / "infra" / "helm" / "nexti"
    parser = argparse.ArgumentParser(prog="airgap", description="NexTI signed update bundles (air-gapped).")
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="save the images, package the chart and sign the bundle")
    build_cmd.add_argument("--key", required=True, type=Path, help="NexTI's private signing key (PEM)")
    build_cmd.add_argument("--passphrase-env")
    build_cmd.add_argument("--chart", type=Path, default=repo_chart)
    build_cmd.add_argument("--sbom-dir", type=Path)
    build_cmd.add_argument("--out", required=True, type=Path)
    for name, help_ in (("verify", "check the signature and every hash"), ("load", "verify, then load the images")):
        cmd = commands.add_parser(name, help=help_)
        cmd.add_argument("bundle", type=Path)
        cmd.add_argument("--public-key", required=True, help="PEM file, PEM text or base64 of the raw key")
        if name == "load":
            cmd.add_argument("--registry", help="local registry to retag the images to, e.g. registry.local:5000")
            cmd.add_argument("--push", action="store_true", help="push the retagged images to --registry")
            cmd.add_argument("--chart-out", type=Path, help="where to copy the chart (default: next to the bundle)")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            key = signing.load_private(args.key, _passphrase(args.passphrase_env))
            manifest = build(args.out, key, args.chart, sbom_dir=args.sbom_dir, run=run)
        else:
            public = signing.load_public_file_or_value(args.public_key)
            if args.command == "verify":
                manifest = verify(args.bundle, public)
            else:
                if args.push and not args.registry:
                    parser.error("--push needs --registry")
                chart_out = args.chart_out or args.bundle.resolve().parent
                manifest = load(
                    args.bundle, public, registry=args.registry, push=args.push, chart_dest=chart_out, run=run
                )
    except (BundleError, signing.SigningKeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except CommandError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"command": args.command, "ok": True, **_summary(manifest)}, indent=2))
    return 0
