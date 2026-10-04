"""Inputs and repository through the API against MinIO, ClamAV and OpenBao (M2 acceptance): a zip with path traversal
is rejected and nothing is stored; an invalid Figma link is rejected; a screenshot goes through the same validation;
versions, downloads, deletion, isolation, fail-closed scanning and the Git connection without SSRF."""

import io
import struct
import uuid
import zipfile
import zlib
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import AppUser, AuditLog, InputArtifact, Membership, ProjectRepository, Role, RoleAssignment
from nexti_core.object_store import ObjectStore, ObjectStoreConfig
from nexti_core.secrets import SecretsConfig, SecretStore, repository_path
from nexti_ingest import ClamdScanner

from .conftest import SETTINGS, World

# The response type of starlette's TestClient (httpx or httpx2, whichever the environment has).
TestResponse = Any

# The EICAR test signature, reversed so no antivirus quarantines this file; it only exists in memory.
EICAR = "*H+H$!ELIF-TSET-SURIVITNA-DRADNATS-RACIE$}7)CC7)^P(45XZP\\4[PA@%P!O5X"[::-1].encode()
GIT = "https://git.bank.example/cards/card-system.git"


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(api_settings.model_copy(update={"dev_auth_enabled": True})), base_url="https://testserver"
    ) as c:
        yield c


def sign_in(api: TestClient, user_id: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user_id)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def png(width: int = 32, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def png_declaring(width: int, height: int) -> bytes:
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    iend = b"IEND"
    return (
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))
        + struct.pack(">I", 0) + iend + struct.pack(">I", zlib.crc32(iend))
    )  # fmt: skip


def store() -> ObjectStore:
    return ObjectStore(
        ObjectStoreConfig(
            SETTINGS.object_store_url, SETTINGS.object_store_access_key,
            SETTINGS.object_store_secret_key.get_secret_value(), SETTINGS.object_store_bucket,
        )
    )  # fmt: skip


def upload(
    api: TestClient, headers: dict[str, str], project: uuid.UUID, name: str, data: bytes, kind: str
) -> TestResponse:
    response: TestResponse = api.post(
        f"/api/v1/projects/{project}/inputs", files={"file": (name, data, "application/octet-stream")},
        data={"kind": kind}, headers=headers,
    )  # fmt: skip
    return response


async def new_member(owner: AsyncEngine, world: World, role_key: str) -> uuid.UUID:
    """A fresh member of tenant A with one base project role in project A."""
    async with owner.begin() as conn:
        user: uuid.UUID = (
            await conn.execute(
                insert(AppUser)
                .values(email=f"m2test-{uuid.uuid4().hex[:8]}@example.test", display_name="Architect")
                .returning(AppUser.id)
            )
        ).scalar_one()
        await conn.execute(insert(Membership).values(tenant_id=world.tenant_a, user_id=user))
        role = (
            await conn.execute(select(Role.id).where(Role.tenant_id == world.tenant_a, Role.key == role_key))
        ).scalar_one()
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=user, role_id=role, scope="project", project_id=world.project_a
            )
        )
    return user


@pytest.fixture
async def admin(api: TestClient, fga: OpenFga, app_engine: AsyncEngine, world: World) -> dict[str, str]:
    await reconcile(app_engine, fga)
    return sign_in(api, world.a_user)


async def test_a_zip_with_path_traversal_is_rejected_and_nothing_is_stored(
    api: TestClient, admin: dict[str, str], owner_engine: AsyncEngine, world: World
) -> None:
    name = f"legacy-{uuid.uuid4().hex[:6]}.zip"
    res = upload(
        api, admin, world.project_a, name, zip_bytes({"ok.cbl": b"ok", "../../etc/cron.d/x": b"evil"}), "source_archive"
    )
    assert res.status_code == 422
    assert res.json()["code"] == "path_traversal"
    input_id = uuid.UUID(res.json()["inputId"])
    async with owner_engine.connect() as conn:
        row = (await conn.execute(select(InputArtifact).where(InputArtifact.id == input_id))).one()
        audited = (
            await conn.execute(
                select(func.count()).where(AuditLog.action == "input.reject", AuditLog.outcome == "failure",
                                           AuditLog.details["input_id"].astext == str(input_id))
            )
        ).scalar_one()  # fmt: skip
    assert (row.status, row.version, row.object_key, row.rejection_code) == ("rejected", None, None, "path_traversal")
    assert audited == 1
    listed = {i["id"]: i for i in api.get(f"/api/v1/projects/{world.project_a}/inputs").json()}
    assert listed[str(input_id)]["status"] == "rejected"


async def test_an_accepted_zip_is_versioned_hashed_and_downloadable_only_with_code_download(
    api: TestClient,
    admin: dict[str, str],
    owner_engine: AsyncEngine,
    fga: OpenFga,
    app_engine: AsyncEngine,
    world: World,
) -> None:
    name = f"card-{uuid.uuid4().hex[:6]}.zip"
    first = zip_bytes({"src/CARD01.cbl": b"       MOVE 1 TO WS-X.\n"})
    v1 = upload(api, admin, world.project_a, name, first, "source_archive")
    assert v1.status_code == 201, v1.text
    v2 = upload(
        api, admin, world.project_a, name, zip_bytes({"src/CARD01.cbl": b"       MOVE 2 TO WS-X.\n"}), "source_archive"
    )
    assert (v1.json()["version"], v2.json()["version"]) == (1, 2)
    assert v1.json()["sha256"] != v2.json()["sha256"]
    assert v1.json()["findings"]["archive"]["entries"] == 1

    content = api.get(f"/api/v1/projects/{world.project_a}/inputs/{v1.json()['id']}/content")
    assert content.status_code == 200
    assert content.content == first
    assert content.headers["content-disposition"].startswith("attachment")
    assert content.headers["x-content-type-options"] == "nosniff"
    # An architect of project A may view the project but not download code.
    architect = await new_member(owner_engine, world, "architect")
    await reconcile(app_engine, fga)
    sign_in(api, architect)
    assert api.get(f"/api/v1/projects/{world.project_a}/inputs/{v1.json()['id']}/content").status_code == 403


async def test_a_target_archive_is_validated_and_guarded_like_the_legacy_code(
    api: TestClient,
    admin: dict[str, str],
    owner_engine: AsyncEngine,
    fga: OpenFga,
    app_engine: AsyncEngine,
    world: World,
) -> None:
    # Flow 4 (ADR-0025): the third party's code and its jar, a zip with the rules of the source archive.
    target = zip_bytes({"src/main/java/App.java": b"class App {}", "app.jar": b"jar"})
    ok = upload(api, admin, world.project_a, f"target-{uuid.uuid4().hex[:6]}.zip", target, "target_archive")
    assert ok.status_code == 201, ok.text
    assert (ok.json()["kind"], ok.json()["findings"]["archive"]["entries"]) == ("target_archive", 2)
    bad = upload(api, admin, world.project_a, "target.zip", zip_bytes({"../x": b"evil"}), "target_archive")
    assert (bad.status_code, bad.json()["code"]) == (422, "path_traversal")
    architect = await new_member(owner_engine, world, "architect")
    await reconcile(app_engine, fga)
    sign_in(api, architect)  # it is code: downloading it needs code.download
    assert api.get(f"/api/v1/projects/{world.project_a}/inputs/{ok.json()['id']}/content").status_code == 403


async def test_a_project_extending_an_application_takes_its_code_and_the_request_documents(
    api: TestClient, admin: dict[str, str], world: World
) -> None:
    # Flow 3 (ADR-0026): the existing Spring Boot application as a source archive and the stories as documents.
    target = {"architecture": "modular-monolith", "backend": "spring-boot", "frontend": "none",
              "database": "postgresql", "cloud": "aws"}  # fmt: skip
    body = {"name": f"Extend {uuid.uuid4().hex[:8]}", "flow": "extendExisting", "pipelineTemplate": "bankStandard",
            "sources": ["spring-boot-app", "user-stories"], "target": target}  # fmt: skip
    created = api.post("/api/v1/projects", json=body, headers=admin)
    assert created.status_code == 201, created.text
    project = uuid.UUID(created.json()["id"])
    app = zip_bytes({"pom.xml": b"<project/>", "src/main/java/App.java": b"class App {}"})
    code = upload(api, admin, project, "billpay.zip", app, "source_archive")
    assert code.status_code == 201, code.text
    assert (code.json()["kind"], code.json()["findings"]["archive"]["entries"]) == ("source_archive", 2)
    story = b"# Refunds\n\nAs a customer I want to request a refund of a payment.\n"
    document = upload(api, admin, project, "refunds.md", story, "document")
    assert document.status_code == 201, document.text
    listed = {i["kind"] for i in api.get(f"/api/v1/projects/{project}/inputs").json() if i["status"] == "accepted"}
    assert listed == {"source_archive", "document"}


async def test_screenshots_go_through_the_same_validation(api: TestClient, admin: dict[str, str], world: World) -> None:
    ok = upload(api, admin, world.project_a, f"login-{uuid.uuid4().hex[:4]}.png", png(), "screenshot")
    assert ok.status_code == 201, ok.text
    assert ok.json()["findings"]["image"] == {"width": 32, "height": 32}
    thumb = api.get(f"/api/v1/projects/{world.project_a}/inputs/{ok.json()['id']}/content")
    assert thumb.headers["content-type"] == "image/png"
    assert thumb.headers["content-disposition"].startswith("inline")
    assert "sandbox" in thumb.headers["content-security-policy"]
    for data, code in (
        (b"not an image at all", "type_not_allowed"),
        (png_declaring(80_000, 80_000), "image_too_large"),
        (png()[:40], "corrupt_image"),
    ):
        res = upload(api, admin, world.project_a, "shot.png", data, "screenshot")
        assert (res.status_code, res.json()["code"]) == (422, code)


async def test_malware_is_rejected(api: TestClient, admin: dict[str, str], world: World) -> None:
    res = upload(api, admin, world.project_a, "notes.txt", EICAR, "document")
    assert res.status_code == 422
    assert res.json()["code"] == "malware_detected"


async def test_without_the_scanner_uploads_fail_closed(api: TestClient, admin: dict[str, str], world: World) -> None:
    api.app.state.inputs.scanner = ClamdScanner("127.0.0.1", 1, timeout_seconds=2)  # type: ignore[attr-defined]
    res = upload(api, admin, world.project_a, "login.png", png(), "screenshot")
    assert res.status_code == 503
    assert res.json()["code"] == "malware_scanner_unavailable"


async def test_without_the_object_store_uploads_fail_closed(
    api: TestClient, admin: dict[str, str], world: World
) -> None:
    api.app.state.inputs.store = ObjectStore(  # type: ignore[attr-defined]
        ObjectStoreConfig("http://127.0.0.1:1", "nobody", "nothing", SETTINGS.object_store_bucket)
    )
    res = upload(api, admin, world.project_a, "login.png", png(), "screenshot")
    assert res.status_code == 503
    assert res.json()["code"] == "storage_unavailable"


async def test_figma_and_prototype_links(api: TestClient, admin: dict[str, str], world: World) -> None:
    url = f"/api/v1/projects/{world.project_a}/inputs:link"
    bad = api.post(url, json={"kind": "figma_link", "url": "https://www.figma.com/community/file/123"}, headers=admin)
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_figma_link")
    good = api.post(
        url, json={"kind": "figma_link", "url": "https://www.figma.com/design/AbCdEf1234567890/Card-Portal"},
        headers=admin,
    )  # fmt: skip
    assert good.status_code == 201, good.text
    assert good.json()["name"] == "Card Portal"
    proto = api.post(
        url, json={"kind": "prototype_link", "url": "https://proto.bank.example/cards", "notes": "Keep the menu"},
        headers=admin,
    )  # fmt: skip
    assert proto.status_code == 201
    assert proto.json()["notes"] == "Keep the menu"
    assert api.get(f"/api/v1/projects/{world.project_a}/inputs/{proto.json()['id']}/content").status_code == 404


async def test_deleting_an_input_removes_its_object(
    api: TestClient, admin: dict[str, str], owner_engine: AsyncEngine, world: World
) -> None:
    res = upload(api, admin, world.project_a, f"x-{uuid.uuid4().hex[:4]}.png", png(), "screenshot")
    input_id = res.json()["id"]
    async with owner_engine.connect() as conn:
        key = (await conn.execute(select(InputArtifact.object_key).where(InputArtifact.id == input_id))).scalar_one()
    assert key is not None
    assert await store().exists(key)
    assert api.delete(f"/api/v1/projects/{world.project_a}/inputs/{input_id}", headers=admin).status_code == 204
    assert not await store().exists(key)
    assert api.get(f"/api/v1/projects/{world.project_a}/inputs/{input_id}/content").status_code == 404
    assert api.delete(f"/api/v1/projects/{world.project_a}/inputs/{input_id}", headers=admin).status_code == 409


async def test_inputs_of_another_tenant_are_unreachable(api: TestClient, admin: dict[str, str], world: World) -> None:
    b = world.project_b
    assert api.get(f"/api/v1/projects/{b}/inputs").status_code in (403, 404)
    assert upload(api, admin, b, "x.png", png(), "screenshot").status_code in (403, 404)
    assert api.put(f"/api/v1/projects/{b}/repository", json={"url": GIT}, headers=admin).status_code in (403, 404)
    # An input of project A addressed through another project id is not found.
    mine = upload(api, admin, world.project_a, f"y-{uuid.uuid4().hex[:4]}.png", png(), "screenshot").json()["id"]
    assert api.get(f"/api/v1/projects/{b}/inputs/{mine}/content").status_code in (403, 404)


async def test_the_repository_token_lives_in_the_secrets_store_and_the_check_has_no_ssrf(
    api: TestClient, admin: dict[str, str], owner_engine: AsyncEngine, world: World
) -> None:
    url = f"/api/v1/projects/{world.project_a}/repository"
    token = f"ghp_{uuid.uuid4().hex}"
    assert (
        api.put(url, json={"url": "http://git.bank.example/x.git"}, headers=admin).json()["code"]
        == "invalid_repository_url"
    )
    saved = api.put(url, json={"url": GIT, "branch": "main", "token": token}, headers=admin)
    assert saved.status_code == 200, saved.text
    assert saved.json()["hasToken"] is True
    assert token not in saved.text
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(select(ProjectRepository).where(ProjectRepository.project_id == world.project_a))
        ).one()
    assert row.vault_path == repository_path(world.tenant_a, world.project_a)
    async with httpx.AsyncClient() as http:
        secrets = SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http)
        assert await secrets.get(row.vault_path) == token

    advertisement = (b"001e# service=git-upload-pack\n0000"
                     b"003d1111111111111111111111111111111111111111 refs/heads/main\n0000")  # fmt: skip

    async def public(host: str, port: int) -> list[str]:
        return ["8.8.8.8"]

    async def internal(host: str, port: int) -> list[str]:
        return ["10.1.2.3"]

    api.app.state.inputs.git_resolver = public  # type: ignore[attr-defined]
    with respx.mock(assert_all_called=False) as router:
        git = router.get(f"{GIT}/info/refs").respond(
            200, content=advertisement, headers={"content-type": "application/x-git-upload-pack-advertisement"}
        )
        router.route().pass_through()
        tested = api.post(f"{url}:test", headers=admin)
        assert tested.status_code == 200, tested.text
        assert tested.json()["status"] == "ok"
        assert tested.json()["branches"] == ["main"]
        assert git.calls.last.request.headers["authorization"].startswith("Basic ")
        api.app.state.inputs.git_resolver = internal  # type: ignore[attr-defined]
        refused = api.post(f"{url}:test", headers=admin)
    assert (refused.status_code, refused.json()["code"]) == (422, "repository_host_not_allowed")
    assert api.get(url).json()["status"] == "failed"

    assert api.delete(url, headers=admin).status_code == 204
    async with httpx.AsyncClient() as http:
        secrets = SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http)
        assert await secrets.get(row.vault_path) is None
    assert api.get(url).json() is None


async def test_loose_code_files_are_packed_validated_and_versioned(
    api: TestClient, admin: dict[str, str], world: World
) -> None:
    """A code input also takes loose code files (a stored procedure, a few programs): they are packed into one zip
    and validated like an uploaded archive; re-uploading the same file makes a new version."""
    url = f"/api/v1/projects/{world.project_a}/inputs"
    name = f"sp_fic_{uuid.uuid4().hex[:6]}.sp"
    one = api.post(url, files={"file": (name, b"create procedure dbo.sp_fic as select 1\n", "text/plain")},
                   data={"kind": "source_archive"}, headers=admin)  # fmt: skip
    assert one.status_code == 201, one.text
    assert (one.json()["name"], one.json()["version"], one.json()["findings"]["archive"]["entries"]) == (name, 1, 1)
    again = api.post(url, files={"file": (name, b"create procedure dbo.sp_fic as select 2\n", "text/plain")},
                     data={"kind": "source_archive"}, headers=admin)  # fmt: skip
    assert again.json()["version"] == 2
    content = api.get(f"{url}/{one.json()['id']}/content", headers=admin).content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == [name]

    several = api.post(url, data={"kind": "source_archive"}, headers=admin, files=[
        ("file", ("PAGO01.cbl", b"       MOVE 1 TO WS-X.\n", "text/plain")),
        ("file", ("PAGO01.cpy", b"       01 WS-X PIC 9.\n", "text/plain")),
    ])  # fmt: skip
    assert several.status_code == 201, several.text
    assert (several.json()["name"], several.json()["findings"]["archive"]["entries"]) == ("PAGO01.cbl (+1).zip", 2)

    for files, code in (
        ([("file", ("tool.exe", b"MZ\x90\x00", "application/octet-stream"))], "unsupported_code_file"),
        ([("file", ("a.sp", b"select 1\n", "text/plain")), ("file", ("a.sp", b"select 2\n", "text/plain"))],
         "duplicate_file"),
        ([("file", ("code.zip", zip_bytes({"x.cbl": b"x\n"}), "application/zip")),
          ("file", ("b.sp", b"select 1\n", "text/plain"))], "mixed_upload"),
        ([("file", ("bin.sp", b"\x00\x01\x02binary", "text/plain"))], "binary_file"),
    ):  # fmt: skip
        refused = api.post(url, data={"kind": "source_archive"}, headers=admin, files=files)
        assert (refused.status_code, refused.json()["code"]) == (422, code), refused.text
    two_docs = api.post(url, data={"kind": "document"}, headers=admin, files=[
        ("file", ("a.md", b"# a\n", "text/markdown")), ("file", ("b.md", b"# b\n", "text/markdown"))])  # fmt: skip
    assert (two_docs.status_code, two_docs.json()["code"]) == (422, "one_file_only")


async def test_a_rejected_upload_can_be_dismissed_from_the_list(
    api: TestClient, admin: dict[str, str], owner_engine: AsyncEngine, world: World
) -> None:
    """Nothing was stored for a rejected upload: deleting it hides it from the list; the rejection and the dismissal
    stay in the audit log."""
    url = f"/api/v1/projects/{world.project_a}/inputs"
    refused = upload(api, admin, world.project_a, f"tool-{uuid.uuid4().hex[:6]}.exe", b"MZ\x90\x00", "source_archive")
    assert refused.status_code == 422
    input_id = refused.json()["inputId"]
    assert input_id in {i["id"] for i in api.get(url, headers=admin).json()}
    assert api.delete(f"{url}/{input_id}", headers=admin).status_code == 204
    assert input_id not in {i["id"] for i in api.get(url, headers=admin).json()}
    async with owner_engine.connect() as conn:
        query = text("SELECT action FROM audit_log WHERE details->>'input_id' = :i ORDER BY id")
        rows = (await conn.execute(query, {"i": input_id})).all()
    actions = [str(row.action) for row in rows]
    assert actions == ["input.reject", "input.dismiss"]
