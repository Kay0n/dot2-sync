"""Temporary: logs Platform M+ buttons, faders and encoders, and lights buttons while held"""

import logging
import threading
import time
from dataclasses import dataclass

from pmpcontroller import PMPController, PMPEvent

log = logging.getLogger(__name__)

SETTLE_SECONDS = 0.3  # a move is finished once its control has been still this long
POLL_SECONDS = 0.05


@dataclass
class Move:
    first_value: float
    last_value: float
    message_count: int
    last_time: float


def run() -> int:
    pmp = PMPController()
    try:
        pmp.connect()
        pmp.reset()
    except OSError as error:
        log.error("%s", error)
        return 1

    moves: dict[str, Move] = {}  # by control name, e.g. "Fader 3"
    moves_lock = threading.Lock()  # rtmidi callbacks run on their own thread

    def record_move(control: str, value: float):
        with moves_lock:
            if move := moves.get(control):
                move.last_value = value
                move.message_count += 1
                move.last_time = time.monotonic()
            else:
                moves[control] = Move(value, value, 1, time.monotonic())

    def log_finished_moves():
        now = time.monotonic()
        with moves_lock:
            finished = [control for control, move in moves.items() if now - move.last_time >= SETTLE_SECONDS]
            for control in finished:
                move = moves.pop(control)
                log.info("%s: %g -> %g (%d messages)", control, move.first_value, move.last_value, move.message_count)

    def button_changed(button_number: int, is_pressed: bool, _is_lit: bool):
        if is_pressed:
            log.info("Button %d", button_number)
        try:
            pmp.set_button_light(button_number, is_pressed)
        except OSError:
            pass

    pmp.add_event_listener(PMPEvent.BUTTON, button_changed)
    pmp.add_event_listener(PMPEvent.FADER, lambda number, value: record_move(f"Fader {number}", round(value, 3)))
    pmp.add_event_listener(PMPEvent.ENCODER, lambda number, value: record_move(f"Encoder {number}", value))
    log.info("Button test: use buttons, faders and encoders to see their numbers, Ctrl+C to stop")
    try:
        next_connection_check = 0.0
        while True:
            log_finished_moves()
            if time.monotonic() >= next_connection_check:
                if not pmp.is_connected():
                    log.error("Platform M+ disconnected")
                    break
                next_connection_check = time.monotonic() + 1
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        if pmp.is_connected():
            pmp.reset()
        pmp.disconnect()
    return 0
