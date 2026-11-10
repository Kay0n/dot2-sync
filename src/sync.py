"""Keeps a dot2 console and an Icon Platform M+ in sync"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass

import status_lights
from dot2 import AuthenticationError, Dot2Client, Dot2Error, Executor, ExecutorGroup, ExecutorKind
from pmpcontroller import PMPController, PMPEvent

log = logging.getLogger(__name__)

StatusLights = Callable[[PMPController], Coroutine]  # a pattern from status_lights

RETRY_SECONDS = 10
CONNECTION_CHECK_SECONDS = 1

# dot2 button executor -> PMP button. Both rows are mirrored: 108 is 24, 101 is 31
DOT2_TO_PMP_BUTTON = {108 - i: 24 + i for i in range(8)} | {208 - i: 16 + i for i in range(8)}
PMP_TO_DOT2_BUTTON = {pmp: dot2 for dot2, pmp in DOT2_TO_PMP_BUTTON.items()}


# dot2 fader executors 1-8 are PMP faders 7-0. PMP fader 8 (master) has no executor
DOT2_TO_PMP_FADER = {executor: 8 - executor for executor in range(1, 9)}
PMP_TO_DOT2_FADER = {pmp: dot2 for dot2, pmp in DOT2_TO_PMP_FADER.items()}


@dataclass(frozen=True)
class DeviceStatus:
    connected: bool = False
    error: str | None = None

    def __str__(self) -> str:
        return "Connected" if self.connected else self.error or "Not connected"


class Dot2PMPSync:
    def __init__(self, dot2_host: str, dot2_password: str):
        self.dot2 = Dot2Client(dot2_host, dot2_password, [
            ExecutorGroup(ExecutorKind.FADER, first=1, count=8),
            ExecutorGroup(ExecutorKind.BUTTON, first=101, count=8),
            ExecutorGroup(ExecutorKind.BUTTON, first=201, count=8),
        ])
        self.pmp = PMPController()
        self.pmp_status = DeviceStatus()
        self.dot2_status = DeviceStatus()
        # sent one at a time so commands stay in order
        self._dot2_commands: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self._pending_fader_positions: dict[int, float] = {}  # by executor
        self._loop: asyncio.AbstractEventLoop | None = None
        self._status_listeners: list[Callable[[], None]] = []
        self._retry_now = asyncio.Event()
        self._dot2_settings_changed = asyncio.Event()
        self._status_lights: StatusLights | None = None
        self._status_lights_task: asyncio.Task | None = None

        self.dot2.add_executor_listener(self._dot2_executor_changed)
        self.pmp.add_event_listener(PMPEvent.FADER, self._pmp_fader_changed)
        self.pmp.add_event_listener(PMPEvent.BUTTON, self._pmp_button_changed)

    @property
    def syncing(self) -> bool:
        return self.pmp_status.connected and self.dot2_status.connected

    def add_status_listener(self, listener: Callable[[], None]):
        """Call `listener()` whenever `pmp_status`, `dot2_status` or `syncing` changes"""
        self._status_listeners.append(listener)

    def retry_connections(self):
        self._retry_now.set()

    def update_dot2_settings(self, dot2_host: str, dot2_password: str):
        self.dot2.host = dot2_host
        self.dot2.password = dot2_password
        self._dot2_settings_changed.set()
        self._retry_now.set()

    async def run(self):
        """Keep both devices connected and in sync until cancelled"""
        self._loop = asyncio.get_running_loop()
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._keep_pmp_connected())
                tasks.create_task(self._keep_dot2_connected())
                tasks.create_task(self._forward_to_dot2())
        finally:
            self._show_status_lights(None)
            self._reset_pmp()
            self.pmp.disconnect()
            await self.dot2.close()

    # -- dot2 -> PMP (called on the event loop) ----------------------------

    def _dot2_executor_changed(self, executor: Executor):
        if self.syncing:
            self._show_on_pmp(executor)

    def _show_on_pmp(self, executor: Executor):
        try:
            if executor.kind is ExecutorKind.FADER:
                fader = DOT2_TO_PMP_FADER[executor.number]
                self.pmp.set_fader(fader, executor.position)
                self.pmp.set_button_light(fader + 8, executor.active)  # SOLO button lights green when fader > 0
            elif executor.number in DOT2_TO_PMP_BUTTON:
                self.pmp.set_button_light(DOT2_TO_PMP_BUTTON[executor.number], executor.active)
        except OSError:
            pass  # an unplugged PMP is noticed by _keep_pmp_connected

    def _show_status_lights(self, pattern: StatusLights | None):
        """Switch to another light pattern, unless it's already showing"""
        if pattern is self._status_lights:
            return
        if self._status_lights_task:
            self._status_lights_task.cancel()
        self._status_lights = pattern
        self._status_lights_task = asyncio.create_task(pattern(self.pmp)) if pattern else None

    def _reset_pmp(self):
        if self.pmp.is_connected():
            with contextlib.suppress(OSError):
                self.pmp.reset()

    # -- PMP -> dot2 (called on the rtmidi thread) -------------------------

    def _pmp_fader_changed(self, fader_number: int, normalized_value: float):
        executor = PMP_TO_DOT2_FADER.get(fader_number)
        if executor is not None and self._loop and self.syncing:
            position = min(max(normalized_value, 0.0), 1.0)
            self._loop.call_soon_threadsafe(self._queue_fader_position, executor, position)

    def _pmp_button_changed(self, button_number: int, is_pressed: bool, is_lit: bool):
        executor = PMP_TO_DOT2_BUTTON.get(button_number)
        if is_pressed and executor is not None:
            self._queue_dot2_command(lambda: self.dot2.set_button(executor, not is_lit))

    def _queue_dot2_command(self, send: Callable[[], Awaitable[None]]):
        if self._loop and self.syncing:
            self._loop.call_soon_threadsafe(self._dot2_commands.put_nowait, send)

    def _queue_fader_position(self, executor: int, position: float):
        """Queue one send per fader, latest position"""
        already_queued = executor in self._pending_fader_positions
        self._pending_fader_positions[executor] = position
        if not already_queued:
            self._dot2_commands.put_nowait(lambda: self._send_latest_fader_position(executor))

    async def _send_latest_fader_position(self, executor: int):
        if (position := self._pending_fader_positions.pop(executor, None)) is not None:
            await self.dot2.set_fader(executor, position)

    async def _forward_to_dot2(self):
        while True:
            send = await self._dot2_commands.get()
            if not self.syncing:
                continue  # meant for a connection that has since dropped
            try:
                await send()
            except Dot2Error as error:  # a lost connection is noticed by _keep_dot2_connected
                log.warning("Could not send to dot2: %s", error)

    # -- connection management ---------------------------------------------

    async def _keep_pmp_connected(self):
        while True:
            if error := self._connect_pmp():
                self._set_status(pmp=DeviceStatus(error=error))
                await self._wait_for_retry()
                continue

            self._set_status(pmp=DeviceStatus(connected=True))
            while self.pmp.is_connected():
                await asyncio.sleep(CONNECTION_CHECK_SECONDS)
            self.pmp.disconnect()
            self._set_status(pmp=DeviceStatus(error="Connection lost"))

    def _connect_pmp(self) -> str | None:
        """Returns an error message, or None on success"""
        try:
            self.pmp.connect()
            self.pmp.reset()  # clear lights left over from before
        except OSError as error:
            self.pmp.disconnect()
            return str(error)
        return None

    async def _keep_dot2_connected(self):
        while True:
            self._dot2_settings_changed.clear()
            if error := await self._connect_dot2():
                self._set_status(dot2=DeviceStatus(error=error))
                await self._wait_for_retry()
                continue

            self._set_status(dot2=DeviceStatus(connected=True))
            while self.dot2.connected and not self._dot2_settings_changed.is_set():
                await asyncio.sleep(CONNECTION_CHECK_SECONDS)
            await self.dot2.close()
            reason = "Reconnecting" if self._dot2_settings_changed.is_set() else "Connection lost"
            self._set_status(dot2=DeviceStatus(error=reason))

    async def _connect_dot2(self) -> str | None:
        """Returns an error message, or None on success"""
        try:
            await self.dot2.connect()
        except AuthenticationError:
            error = "Login rejected, check the password"
        except (OSError, Dot2Error) as exception:
            error = f"Can't reach dot2 at {self.dot2.host}"
            if self.dot2_status.error != error:  # log details once, not every retry
                log.warning("%s", exception)
        else:
            return None
        await self.dot2.close()
        return error

    async def _wait_for_retry(self):
        """Wait RETRY_SECONDS, or less if retry_connections() is called"""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._retry_now.wait(), RETRY_SECONDS)
        self._retry_now.clear()

    def _set_status(self, pmp: DeviceStatus | None = None, dot2: DeviceStatus | None = None):
        was_syncing = self.syncing
        old = (self.pmp_status, self.dot2_status)
        self.pmp_status = pmp or self.pmp_status
        self.dot2_status = dot2 or self.dot2_status
        if (self.pmp_status, self.dot2_status) == old:
            return

        log.info("Platform M+: %s | dot2: %s", self.pmp_status, self.dot2_status)
        if self.syncing and not was_syncing:
            log.info("Sync active")
            for executor in list(self.dot2.executors.values()):  # later changes arrive via _dot2_executor_changed
                self._show_on_pmp(executor)
        elif was_syncing and not self.syncing:
            log.info("Sync stopped")
            self._pending_fader_positions.clear()
            self._reset_pmp()

        if self.syncing:
            self._show_status_lights(status_lights.sync_started)
        elif self.pmp_status.connected:
            self._show_status_lights(status_lights.waiting_for_dot2)
        else:
            self._show_status_lights(None)

        for listener in list(self._status_listeners):
            try:
                listener()
            except Exception:
                log.exception("Status listener failed")
