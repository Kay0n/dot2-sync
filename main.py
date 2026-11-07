import asyncio
import logging
from collections.abc import Awaitable, Callable

from dot2 import Dot2Client, Dot2Error, Executor, ExecutorGroup, ExecutorKind
from pmpcontroller import PMPController, PMPEvent

DOT2_HOST = "127.0.0.1"
DOT2_PASSWORD = "password"
RETRY_SECONDS = 10
SYNC_INDICATOR_BUTTON = 86  # blue light on the PMP while syncing

# dot2 button executor -> PMP button. Both rows are mirrored: 108 is 24, 101 is 31
DOT2_TO_PMP_BUTTON = {108 - i: 24 + i for i in range(8)} | {208 - i: 16 + i for i in range(8)}
PMP_TO_DOT2_BUTTON = {pmp: dot2 for dot2, pmp in DOT2_TO_PMP_BUTTON.items()}


def fader_to_pmp(executor: int) -> int:
    """dot2 fader executors 1-8 are PMP faders 7-0 (and back again)"""
    return 8 - executor


class Dot2PMPSync:
    def __init__(self):
        self.dot2 = Dot2Client(DOT2_HOST, DOT2_PASSWORD, [
            ExecutorGroup(ExecutorKind.FADER, first=1, count=8),
            ExecutorGroup(ExecutorKind.BUTTON, first=101, count=8),
            ExecutorGroup(ExecutorKind.BUTTON, first=201, count=8),
        ])
        self.platform_m = PMPController()
        self.dot2_commands: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None

        self.dot2.add_listener(self.dot2_changed)
        self.platform_m.add_event_listener(PMPEvent.FADER, self.pmp_fader_changed)
        self.platform_m.add_event_listener(PMPEvent.BUTTON, self.pmp_button_changed)

    # -- dot2 -> PMP (called on the event loop) ----------------------------

    def dot2_changed(self, executor: Executor):
        if not self.platform_m.is_connected():
            return
        if executor.kind is ExecutorKind.FADER:
            fader = fader_to_pmp(executor.number)
            self.platform_m.set_fader(fader, executor.position)
            self.platform_m.set_button(fader + 8, executor.active)  # SOLO button lights green when fader > 0
        elif executor.number in DOT2_TO_PMP_BUTTON:
            self.platform_m.set_button(DOT2_TO_PMP_BUTTON[executor.number], executor.active)

    # -- PMP -> dot2 (called on the rtmidi thread) -------------------------

    def pmp_fader_changed(self, fader_number: int, normalized_value: float):
        executor = fader_to_pmp(fader_number)
        if executor >= 1:  # PMP fader 8 (master) has no dot2 executor
            position = min(max(normalized_value, 0.0), 1.0)
            self.queue_dot2_command(lambda: self.dot2.set_fader(executor, position))

    def pmp_button_changed(self, button_number: int, is_pressed: bool, button_state: bool):
        executor = PMP_TO_DOT2_BUTTON.get(button_number)
        if is_pressed and executor is not None:
            self.queue_dot2_command(lambda: self.dot2.set_button(executor, not button_state))

    def queue_dot2_command(self, send: Callable[[], Awaitable[None]]):
        if self.loop and self.dot2.connected:
            self.loop.call_soon_threadsafe(self.dot2_commands.put_nowait, send)

    # -- connection management ---------------------------------------------

    async def connect(self):
        """Connect to both devices, retrying until it works"""
        while True:
            try:
                self.platform_m.connect()
                await self.dot2.connect()
                break
            except (OSError, Dot2Error) as error:
                print(f"{error}; retrying in {RETRY_SECONDS}s")
                await self.disconnect()
                await asyncio.sleep(RETRY_SECONDS)
        print("Connected, now syncing Dot2 to Platform M+")
        self.platform_m.set_button(SYNC_INDICATOR_BUTTON, True)

    async def disconnect(self):
        await self.dot2.close()
        if self.platform_m.is_connected():
            self.platform_m.reset()
        self.platform_m.disconnect()
        while not self.dot2_commands.empty():  # drop commands meant for the old connection
            self.dot2_commands.get_nowait()

    async def forward_to_dot2(self):
        """Send queued PMP changes to dot2 until either side disconnects"""
        while self.platform_m.is_connected() and self.dot2.connected:
            try:
                send = await asyncio.wait_for(self.dot2_commands.get(), timeout=0.5)
            except TimeoutError:
                continue  # re-check the connections
            await send()

    async def run(self):
        self.loop = asyncio.get_running_loop()
        try:
            while True:
                await self.connect()
                try:
                    await self.forward_to_dot2()
                except (OSError, Dot2Error):
                    pass
                print("Lost connection, reconnecting")
                await self.disconnect()
        finally:
            await self.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(Dot2PMPSync().run())
