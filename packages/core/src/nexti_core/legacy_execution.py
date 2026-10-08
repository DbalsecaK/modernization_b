"""How a project's legacy runs for the golden master (ADR-0052), shared by the API (the setting and its connection
test) and the worker (the runner it picks).

- `auto`: by the inputs, as before: recorded traces when the archive has them, otherwise the engine of the platform
  (Sybase ASE).
- `traces`: only recorded traces; without them the phase waits. The verdict cannot pass PARTLY PROVEN.
- `live`: the legacy runs on a system of the customer (`kind`: an IBM i first). Cases with fresh inputs can be
  observed, so the verdict can reach PROVEN.

The system's address and options live in `config`; its credentials only in the secrets store (ADR-0007)."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Mode = Literal["auto", "traces", "live"]
Kind = Literal["ibmi"]
MODES: tuple[Mode, ...] = ("auto", "traces", "live")
KINDS: tuple[Kind, ...] = ("ibmi",)

# The IBM i host servers (as-signon 8476, as-rmtcmd 8475, as-database 8471...) and their TLS ports; 446 is DRDA.
IBMI_PORTS = (446, 449, 8470, 8471, 8472, 8473, 8474, 8475, 8476, 9470, 9471, 9472, 9473, 9474, 9475, 9476)
_IBMI_NAME = re.compile(r"^[A-Z#$@][A-Z0-9#$@_.]{0,9}$")
_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}"
                   r"[A-Za-z0-9])?)*$")  # fmt: skip


class IbmiConfig(BaseModel):
    """Where an IBM i is and the test library the golden master may write: the cases' rows are loaded there and the
    programs are called with it first in the library list. Never a production library."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=253)
    port: int = 8476  # the sign-on server: answers when the host servers are started
    library: str = Field(min_length=1, max_length=10)
    programs: str | None = Field(default=None, max_length=10)  # the library of the programs, if not `library`
    ccsid: int = Field(default=284, ge=1, le=65535)  # 284: EBCDIC Spanish
    tls: bool = False

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        if not _HOST.match(value):
            raise ValueError("a host name or IPv4 address, without scheme, port or path")
        return value.lower()

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if value not in IBMI_PORTS:
            raise ValueError(f"one of the IBM i host server ports: {', '.join(map(str, IBMI_PORTS))}")
        return value

    @field_validator("library", "programs")
    @classmethod
    def _library(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.upper()
        if not _IBMI_NAME.match(upper):
            raise ValueError("an IBM i name: up to 10 characters, a letter or #$@ first")
        return upper


class Credentials(BaseModel):
    """What the secrets store keeps for a live system, as JSON."""

    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


CONFIGS: dict[str, type[IbmiConfig]] = {"ibmi": IbmiConfig}


def checked_config(kind: str, config: dict[str, object]) -> dict[str, object]:
    """The configuration of a kind of live system, validated and normalised. Raises ValueError."""
    model = CONFIGS.get(kind)
    if model is None:
        raise ValueError(f"unknown kind of live system: {kind}")
    return model.model_validate(config).model_dump()


__all__ = ["CONFIGS", "IBMI_PORTS", "KINDS", "MODES", "Credentials", "IbmiConfig", "Kind", "Mode", "checked_config"]
