"""Platform M+ lights that show the sync state"""

import asyncio
import contextlib

from pmpcontroller import PMPController

WAITING_BUTTON = 0  # red. TODO: the button on the side, found with --button-test
SYNC_INDICATOR_BUTTON = 86  # blue
WAITING_FLASH_SECONDS = 0.5
FLASH_SECONDS = 0.15


async def waiting_for_dot2(pmp: PMPController):
    """Flash the red light until cancelled"""
    try:
        while True:
            pmp.set_button_light(WAITING_BUTTON, True)
            await asyncio.sleep(WAITING_FLASH_SECONDS)
            pmp.set_button_light(WAITING_BUTTON, False)
            await asyncio.sleep(WAITING_FLASH_SECONDS)
    except OSError:
        pass  # an unplugged PMP is noticed by the sync
    finally:
        with contextlib.suppress(OSError):
            pmp.set_button_light(WAITING_BUTTON, False)


async def sync_started(pmp: PMPController):
    """Flash the blue light, then leave it on"""
    with contextlib.suppress(OSError):
        for _ in range(3):
            pmp.set_button_light(SYNC_INDICATOR_BUTTON, True)
            await asyncio.sleep(FLASH_SECONDS)
            pmp.set_button_light(SYNC_INDICATOR_BUTTON, False)
            await asyncio.sleep(FLASH_SECONDS)
        pmp.set_button_light(SYNC_INDICATOR_BUTTON, True)
