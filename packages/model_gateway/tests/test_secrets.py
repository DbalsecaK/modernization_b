import uuid

import httpx

from nexti_model_gateway.secrets import SecretsConfig, SecretStore, connection_path

from .conftest import ENV, needs_openbao


def store(http: httpx.AsyncClient) -> SecretStore:
    config = SecretsConfig(url=f"http://127.0.0.1:{ENV.get('OPENBAO_PORT', '8210')}", token=ENV["OPENBAO_DEV_ROOT_SECRET"])
    return SecretStore(config, http)


@needs_openbao
async def test_a_secret_is_written_read_and_deleted() -> None:
    path = connection_path(uuid.uuid4(), uuid.uuid4())
    async with httpx.AsyncClient(timeout=10) as http:
        secrets = store(http)
        assert await secrets.healthy()
        assert await secrets.get(path) is None
        await secrets.put(path, "sk-or-test-value")
        assert await secrets.get(path) == "sk-or-test-value"
        await secrets.put(path, "sk-or-rotated")
        assert await secrets.get(path) == "sk-or-rotated"
        await secrets.delete(path)
        assert await secrets.get(path) is None


@needs_openbao
async def test_a_wrong_token_cannot_read() -> None:
    path = connection_path(uuid.uuid4(), uuid.uuid4())
    async with httpx.AsyncClient(timeout=10) as http:
        await store(http).put(path, "x")
        intruder = SecretStore(SecretsConfig(url=store(http).config.url, token="wrong"), http)
        try:
            await intruder.get(path)
        except Exception as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("a wrong token read the secret")
        await store(http).delete(path)
