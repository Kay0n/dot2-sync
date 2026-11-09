"""High-level dot2 client: executor state, change listeners and commands"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterable

from . import protocol
from .connection import Connection
from .models import Dot2Error, Executor, ExecutorGroup

log = logging.getLogger(__name__)

Listener = Callable[[Executor], None]


class Dot2Client:
    def __init__(self, host: str, password: str, groups: Iterable[ExecutorGroup] = (), *, timeout: float = 5.0):
        self.host = host
        self.executors: dict[int, Executor] = {}  # last known state, by executor number
        self.password = password
        self._groups = list(groups)
        self._timeout = timeout
        self._listeners: list[Listener] = []
        self._connection: Connection | None = None
        self._updates_task: asyncio.Task | None = None

    # -- connection --------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connection is not None and not self._connection.closed

    async def connect(self) -> None:
        """Connect and start watching executors. Raises Dot2Error on failure"""
        self._connection = await Connection.open(self.host, self.password, self._timeout)
        self._updates_task = asyncio.create_task(self._receive_updates())
        await self._request_playbacks()

    async def close(self) -> None:
        if self._updates_task:
            self._updates_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._updates_task
        if self._connection:
            await self._connection.close()
        self._connection = None
        self._updates_task = None
        self.executors.clear()

    async def __aenter__(self) -> Dot2Client:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # -- commands ----------------------------------------------------------

    async def command(self, text: str) -> None:
        """Send a command line, exactly as typed on the console. Raises Dot2Error if not connected"""
        if not self.connected:
            raise Dot2Error("Not connected")
        try:
            await self._connection.send(protocol.command(text))
        except ConnectionError as error:
            raise Dot2Error("Connection lost") from error

    async def set_fader(self, number: int, position: float) -> None:
        """Move executor `number` to `position` (0.0-1.0)"""
        if not 0.0 <= position <= 1.0:
            raise ValueError("position must be between 0.0 and 1.0")
        await self.command(f"Executor {number} At {position * 100:g}")

    async def set_button(self, number: int, active: bool) -> None:
        await self.command(f"{'On' if active else 'Off'} Executor {number}")

    # -- state updates -----------------------------------------------------

    def add_executor_listener(self, listener: Listener) -> Callable[[], None]:
        """Returns a function that removes it"""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def _receive_updates(self) -> None:
        # Each playbacks request is answered once, so each answer sends the next.
        # A re-login drops pending requests, so it restarts the chain too
        try:
            async for message in self._connection.messages():
                if protocol.is_playbacks(message):
                    self._update(protocol.parse_playbacks(message))
                    await self._request_playbacks()
                elif protocol.is_login_reply(message):
                    await self._request_playbacks()
            log.warning("dot2 at %s closed the connection", self.host)
        except Exception:
            log.exception("Lost connection to dot2 at %s", self.host)
            await self._connection.close()

    async def _request_playbacks(self) -> None:
        if self._groups:
            await self._connection.send(protocol.playbacks_request(self._groups))

    def _update(self, executors: list[Executor]) -> None:
        """Store new executor states and tell listeners about the ones that changed"""
        for executor in executors:
            if self.executors.get(executor.number) == executor:
                continue
            self.executors[executor.number] = executor
            for listener in list(self._listeners):
                try:
                    listener(executor)
                except Exception:
                    log.exception("dot2 listener failed")
