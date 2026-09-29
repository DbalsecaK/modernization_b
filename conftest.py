"""Shared pytest setup. On Windows, psycopg's async mode needs the selector event loop (the default proactor loop is
not supported); Linux and CI already use a selector loop."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined,unused-ignore]
