"""Malware scanning with ClamAV (`clamd`, INSTREAM over TCP; ADR-0008). The file is streamed from memory or from
the upload's spool; nothing is written to a shared disk."""

import asyncio
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO

from nexti_ingest.errors import ScannerUnavailableError

CHUNK = 64 * 1024


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class ClamdScanner:
    def __init__(self, host: str, port: int = 3310, timeout_seconds: float = 120) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout_seconds

    async def _exchange(self, command: bytes, chunks: Iterable[bytes] = ()) -> str:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=10)
        except (OSError, TimeoutError) as exc:
            raise ScannerUnavailableError(f"clamd at {self.host}:{self.port} is not reachable") from exc
        try:
            writer.write(command)
            for chunk in chunks:
                writer.write(struct.pack(">I", len(chunk)) + chunk)
                await writer.drain()
            if command == b"zINSTREAM\0":
                writer.write(struct.pack(">I", 0))
            await writer.drain()
            reply = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=self.timeout)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ScannerUnavailableError("clamd did not answer") from exc
        finally:
            writer.close()
        return reply.rstrip(b"\0").decode("utf-8", errors="replace")

    async def ping(self) -> bool:
        return await self._exchange(b"zPING\0") == "PONG"

    async def scan_chunks(self, chunks: Iterable[bytes]) -> ScanResult:
        reply = await self._exchange(b"zINSTREAM\0", chunks)
        if reply.endswith(" FOUND"):
            return ScanResult(False, reply.removeprefix("stream: ").removesuffix(" FOUND"))
        if reply.endswith("OK"):
            return ScanResult(True)
        # "INSTREAM size limit exceeded", "... ERROR": the file could not be scanned, which is not "clean".
        raise ScannerUnavailableError(f"clamd could not scan the file: {reply}")

    async def scan(self, stream: BinaryIO) -> ScanResult:
        stream.seek(0)

        def chunks() -> Iterable[bytes]:
            while chunk := stream.read(CHUNK):
                yield chunk

        try:
            return await self.scan_chunks(chunks())
        finally:
            stream.seek(0)
