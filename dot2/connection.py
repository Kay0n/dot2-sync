"""A logged-in websocket session with a dot2 console

Handles everything session-related (login, keep-alive, re-login) so that
callers only see application messages
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import AsyncIterator, Callable

import aiohttp

from . import protocol
from .models import AuthenticationError, Dot2Error
from .protocol import Message

KEEP_ALIVE_SECONDS = 15


class Connection:
    """Use `await Connection.open(...)` rather than the constructor"""

    def __init__(self, http: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse, password: str):
        self._http = http
        self._ws = ws
        self._password_md5 = hashlib.md5(password.encode()).hexdigest()
        self._session_id = 0  # 0 asks the console for a new session
        self._keep_alive_task: asyncio.Task | None = None

    @classmethod
    async def open(cls, host: str, password: str, timeout: float = 5.0) -> Connection:
        """Connect and log in. Raises AuthenticationError or Dot2Error"""
        http = aiohttp.ClientSession()
        try:
            async with asyncio.timeout(timeout):
                ws = await http.ws_connect(f"ws://{host}/?ma=1")
                connection = cls(http, ws, password)
                await connection._log_in()
        except (aiohttp.ClientError, OSError) as error:  # OSError includes TimeoutError
            await http.close()
            raise Dot2Error(f"Could not connect to dot2 at {host}: {error!r}") from error
        except BaseException:
            await http.close()
            raise

        connection._keep_alive_task = asyncio.create_task(connection._keep_alive())
        return connection

    @property
    def closed(self) -> bool:
        return self._ws.closed

    async def send(self, message: Message) -> None:
        """Send a message. Raises ConnectionError if the socket is closed"""
        payload = {**message, "session": self._session_id}
        await self._ws.send_str(json.dumps(payload, separators=(",", ":")))

    async def messages(self) -> AsyncIterator[Message]:
        """Yield incoming messages until the connection closes"""
        while (message := await self._receive()) is not None:
            if message.get("forceLogin"):  # the session expired; log in again
                await self.send(protocol.login(self._password_md5))
            else:
                yield message

    async def close(self) -> None:
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if not self._ws.closed:
            with contextlib.suppress(ConnectionError):
                await self.send(protocol.close())
            await self._ws.close()
        await self._http.close()

    async def _log_in(self) -> None:
        await self._receive_until(lambda m: "appType" in m)  # console greeting
        await self.send({})  # request a session (sent with session id 0)
        await self._receive_until(lambda m: m.get("forceLogin"))
        await self.send(protocol.login(self._password_md5))
        reply = await self._receive_until(protocol.is_login_reply)
        if not reply.get("result"):
            raise AuthenticationError("Login rejected; check the password")

    async def _keep_alive(self) -> None:
        while not self.closed:
            await asyncio.sleep(KEEP_ALIVE_SECONDS)
            with contextlib.suppress(ConnectionError):
                await self.send({})

    async def _receive_until(self, predicate: Callable[[Message], bool]) -> Message:
        while (message := await self._receive()) is not None:
            if predicate(message):
                return message
        raise ConnectionError("Connection closed during login")

    async def _receive(self) -> Message | None:
        """Return the next JSON message, or None once the connection is closed"""
        async for raw in self._ws:  # stops when the socket closes
            if raw.type is aiohttp.WSMsgType.TEXT:
                message = json.loads(raw.data)
                if message.get("session"):
                    self._session_id = message["session"]
                return message
        return None
