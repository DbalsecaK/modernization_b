"""The generated code through the API (spec 18.3, tab "Código"; plan P2 step 2): the file tree of the newest
generation without the pipeline's working material, one file, and the zip, which is audited."""

import io
import uuid
import zipfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import execute
from .test_runs_api import sign_in
from .test_validation_api import seeded

JAVA = "src/main/java/demo/PayOrderService.java"


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _with_design(owner: AsyncEngine, project_id: uuid.UUID) -> None:
    """A design document in the same run: working material the tree must not show."""
    await execute(
        owner,
        "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, sha256, size_bytes) "
        "SELECT tenant_id, project_id, run_id, 'docs', 'design/design.json', object_key, sha256, size_bytes "
        "FROM generated_artifact WHERE project_id = :p",
        p=project_id,
    )


async def test_the_tree_one_file_and_the_zip(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    await _with_design(owner_engine, project_id)
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}/code"
    tree = api.get(base, headers=headers).json()
    assert [(f["path"], f["layer"], f["rules"]) for f in tree["files"]] == [(JAVA, "domain", ["RULE-001"])]
    file = api.get(f"{base}/file", params={"path": JAVA}, headers=headers).json()
    assert "RULE-001" in file["content"]
    assert (file["truncated"], file["sizeBytes"]) == (False, len(file["content"].encode()))
    for path in ("design/design.json", "../secrets", "PayOrderService.java"):
        assert api.get(f"{base}/file", params={"path": path}, headers=headers).status_code == 404
    download = api.get(f"{base}:download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(download.content)).namelist() == [JAVA]
    async with owner_engine.connect() as conn:
        audited = (
            await conn.execute(
                text("SELECT count(*) FROM audit_log WHERE action = 'code.download' AND target = :t"),
                {"t": f"project:{project_id}"},
            )
        ).scalar()
    assert audited == 1


async def test_without_generated_code_there_is_nothing_to_show(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    await execute(owner_engine, "DELETE FROM generated_artifact WHERE project_id = :p", p=project_id)
    headers = sign_in(api, world.a_user)
    assert api.get(f"/api/v1/projects/{project_id}/code", headers=headers).json() is None
    assert api.get(f"/api/v1/projects/{project_id}/code:download", headers=headers).status_code == 404


async def test_the_code_of_another_tenant_is_unreachable(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.b_user)
    base = f"/api/v1/projects/{project_id}/code"
    for path in (base, f"{base}/file?path={JAVA}", f"{base}:download"):
        assert api.get(path, headers=headers).status_code in (403, 404)
