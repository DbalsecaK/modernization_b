"""Server-side sessions in Redis (spec 15.1).

- The cookie holds only a random id. Redis keys are the SHA-256 of that id, so a Redis dump yields no
  usable cookie, and the stored record is encrypted (it holds the Keycloak refresh token).
- Idle timeout slides on every request; the absolute lifetime never extends. A new id is issued at login.
- Mutating requests need the session's CSRF token in X-CSRF-Token, and a matching Origin when one is sent.
- Each user has an index of their session keys, so a deactivation (SCIM) can end their sessions at once.
"""

import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from redis.asyncio import Redis

from nexti_api.errors import ProblemError
from nexti_api.settings import Settings

AuthMethod = Literal["keycloak", "dev-auth"]
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOGIN_STATE_TTL_SECONDS = 600


def session_cookie_name(settings: Settings) -> str:
    return "__Host-nexti_session" if settings.session_cookie_secure else "nexti_session"


def login_cookie_name(settings: Settings) -> str:
    return "__Host-nexti_login" if settings.session_cookie_secure else "nexti_login"


@dataclass(frozen=True)
class Session:
    user_id: uuid.UUID
    auth_method: AuthMethod
    csrf_token: str
    created_at: float
    active_tenant_id: uuid.UUID | None = None
    keycloak_sub: str | None = None
    refresh_token: str | None = None

    def to_json(self) -> bytes:
        data = asdict(self)
        data["user_id"] = str(self.user_id)
        data["active_tenant_id"] = str(self.active_tenant_id) if self.active_tenant_id else None
        return json.dumps(data).encode()

    @classmethod
    def from_json(cls, raw: bytes) -> "Session":
        data = json.loads(raw)
        data["user_id"] = uuid.UUID(data["user_id"])
        data["active_tenant_id"] = uuid.UUID(data["active_tenant_id"]) if data["active_tenant_id"] else None
        return cls(**data)


def _fernet(secret: str) -> Fernet:
    # Any strong secret works: it is stretched to the 32-byte key Fernet expects.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


class SessionStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        secret = settings.session_secret.get_secret_value()
        if not secret:
            raise RuntimeError("SESSION_SECRET is not set")
        self.redis = redis
        self.fernet = _fernet(secret)
        self.idle = settings.session_idle_seconds
        self.max = settings.session_max_seconds

    @staticmethod
    def _key(prefix: str, token: str) -> str:
        return f"nexti:{prefix}:{hashlib.sha256(token.encode()).hexdigest()}"

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        auth_method: AuthMethod,
        active_tenant_id: uuid.UUID | None,
        keycloak_sub: str | None = None,
        refresh_token: str | None = None,
    ) -> tuple[str, Session]:
        session_id = secrets.token_urlsafe(32)
        session = Session(
            user_id=user_id,
            auth_method=auth_method,
            csrf_token=secrets.token_urlsafe(32),
            created_at=time.time(),
            active_tenant_id=active_tenant_id,
            keycloak_sub=keycloak_sub,
            refresh_token=refresh_token,
        )
        await self._write(session_id, session)
        return session_id, session

    async def _write(self, session_id: str, session: Session) -> None:
        remaining = int(session.created_at + self.max - time.time())
        key = self._key("session", session_id)
        index = self._key("user-sessions", str(session.user_id))
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.set(key, self.fernet.encrypt(session.to_json()), ex=max(1, min(self.idle, remaining)))
            pipe.sadd(index, key)
            pipe.expire(index, self.max)
            await pipe.execute()

    async def revoke_user(self, user_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> int:
        """Ends the sessions of a user (only those whose active tenant is `tenant_id`, when given). Returns how many."""
        index = self._key("user-sessions", str(user_id))
        ended = 0
        for raw_key in await self.redis.smembers(index):
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            raw = await self.redis.get(key)
            if raw is not None and tenant_id is not None:
                try:
                    if Session.from_json(self.fernet.decrypt(raw)).active_tenant_id != tenant_id:
                        continue
                except (InvalidToken, ValueError, KeyError, TypeError):
                    pass  # unreadable: ended like the others
            ended += int(await self.redis.delete(key))
            await self.redis.srem(index, key)
        return ended

    async def get(self, session_id: str) -> Session | None:
        """The session, with its idle timeout renewed; None if unknown, idle too long or past its lifetime."""
        raw = await self.redis.get(self._key("session", session_id))
        if raw is None:
            return None
        try:
            session = Session.from_json(self.fernet.decrypt(raw))
        except (InvalidToken, ValueError, KeyError, TypeError):
            await self.delete(session_id)
            return None
        if time.time() >= session.created_at + self.max:
            await self.delete(session_id)
            return None
        await self._write(session_id, session)
        return session

    async def update(self, session_id: str, session: Session, **changes: object) -> Session:
        updated = replace(session, **changes)  # type: ignore[arg-type]
        await self._write(session_id, updated)
        return updated

    async def delete(self, session_id: str) -> None:
        await self.redis.delete(self._key("session", session_id))

    # Pending logins: state -> (browser binding, nonce, PKCE verifier, return path). Single use.
    async def save_login(self, state: str, data: dict[str, str]) -> None:
        payload = self.fernet.encrypt(json.dumps(data).encode())
        await self.redis.set(self._key("login", state), payload, ex=LOGIN_STATE_TTL_SECONDS)

    async def pop_login(self, state: str) -> dict[str, str] | None:
        raw = await self.redis.getdel(self._key("login", state))
        if raw is None:
            return None
        try:
            data: dict[str, str] = json.loads(self.fernet.decrypt(raw))
        except (InvalidToken, ValueError):
            return None
        return data


@dataclass(frozen=True)
class CurrentSession:
    id: str
    data: Session


async def optional_session(request: Request) -> CurrentSession | None:
    settings: Settings = request.app.state.settings
    session_id = request.cookies.get(session_cookie_name(settings))
    if not session_id:
        return None
    store: SessionStore | None = request.app.state.sessions
    if store is None:
        raise ProblemError(503, "sessions_unavailable", "Sessions are not configured.")
    data = await store.get(session_id)
    return CurrentSession(session_id, data) if data else None


async def require_session(request: Request) -> CurrentSession:
    """The signed-in session; for mutating methods also checks CSRF and Origin."""
    current = await optional_session(request)
    if current is None:
        raise ProblemError(401, "not_authenticated", "Sign in to continue.")
    if request.method not in SAFE_METHODS:
        check_csrf(request, current.data)
    return current


def check_csrf(request: Request, session: Session) -> None:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != settings.web_origin.rstrip("/"):
        raise ProblemError(403, "origin_not_allowed", "The request comes from an origin that is not allowed.")
    token = request.headers.get(CSRF_HEADER, "")
    if not token or not secrets.compare_digest(token, session.csrf_token):
        raise ProblemError(403, "csrf_failed", "The CSRF token is missing or invalid.")
