from collections.abc import Callable
from enum import Enum, auto

import rtmidi

PORT_NAME = "Platform M+"
NOTE_ON = 0x90
CONTROL_CHANGE = 0xB0
PITCH_BEND = 0xE0
VELOCITY_ON = 127
VELOCITY_OFF = 0
MAX_7BIT = 0x7F
MAX_FADER_VALUE = 14896  # the device's max, not the full 14 bits
FADER_COUNT = 9  # 8 channel faders and the master
BUTTON_COUNT = 100  # note numbers cleared by reset()
FADER_TOUCH_NOTE = 104  # fader 0's touch note, up to 112 for the master


class PMPEvent(Enum):
    FADER = auto()
    FADER_TOUCH = auto()
    BUTTON = auto()
    ENCODER = auto()


class PMPController:
    """Event listeners are called on rtmidi's input thread"""

    def __init__(self, motors_follow_moves: bool = False):
        self.connected = False
        self.motors_follow_moves = motors_follow_moves
        self.midi_in = rtmidi.MidiIn()
        self.midi_out = rtmidi.MidiOut()
        self.fader_positions = [0.0] * FADER_COUNT
        self.faders_touched = [False] * FADER_COUNT
        self.button_lights: dict[int, bool] = {}
        self.event_callbacks: dict[PMPEvent, list[Callable]] = {event: [] for event in PMPEvent}

    def connect(self) -> tuple[int, int]:
        """Returns the in and out port numbers. Raises OSError if the device is missing or busy"""
        in_port = self._find_port(self.midi_in)
        out_port = self._find_port(self.midi_out)
        if in_port is None or out_port is None:
            raise OSError("Platform M+ not found")
        try:
            self.midi_in.open_port(in_port)
            self.midi_out.open_port(out_port)
        except rtmidi.RtMidiError as error:  # e.g. another program has the port open
            self.disconnect()
            raise OSError(f"Could not open Platform M+: {error}") from error
        self.midi_in.set_callback(self._process_midi_message)
        self.connected = True
        return (in_port, out_port)

    def disconnect(self):
        self.connected = False
        self.midi_in.cancel_callback()
        self.midi_in.close_port()
        self.midi_out.close_port()

    def is_connected(self) -> bool:
        """Checks the port list, so it notices an unplug even when nothing has been sent"""
        if self.connected and self._find_port(self.midi_in) is None:
            self.connected = False
        return self.connected

    # -- output ----------------------------------------------------------------

    def set_fader(self, fader_number: int, normalized_position: float):
        """Move fader 0-8 to a position from 0 to 1. Raises OSError if disconnected"""
        if 0 <= fader_number < FADER_COUNT:
            normalized_position = min(max(normalized_position, 0.0), 1.0)
            value = int(normalized_position * MAX_FADER_VALUE)
            msb = (value >> 7) & MAX_7BIT
            lsb = value & MAX_7BIT
            self._send([PITCH_BEND + fader_number, lsb, msb])
            self.fader_positions[fader_number] = normalized_position

    def set_button_light(self, button_number: int, is_lit: bool):
        """Raises OSError if disconnected"""
        self.button_lights[button_number] = is_lit
        self._send([NOTE_ON, button_number, VELOCITY_ON if is_lit else VELOCITY_OFF])

    def reset(self):
        """Move all faders to 0 and turn all buttons off. Raises OSError if disconnected"""
        for fader_number in range(FADER_COUNT):
            self.set_fader(fader_number, 0)
        for button_number in range(BUTTON_COUNT):
            self.set_button_light(button_number, False)

    def set_motors_follow_moves(self, motors_follow_moves: bool):
        self.motors_follow_moves = motors_follow_moves

    def get_fader(self, fader_number: int) -> float:
        """The last position (0 to 1) fader 0-8 was set or moved to"""
        return self.fader_positions[fader_number]

    def is_fader_touched(self, fader_number: int) -> bool:
        return self.faders_touched[fader_number]

    def get_button_light(self, button_number: int) -> bool:
        return self.button_lights.get(button_number, False)

    # -- input -----------------------------------------------------------------

    def add_event_listener(self, event_type: PMPEvent, callback: Callable):
        """Callback signatures:
            FADER:   callback(fader_number: int, normalized_value: float)
            FADER_TOUCH: callback(fader_number: int, is_touched: bool)
            BUTTON:  callback(button_number: int, is_pressed: bool, is_lit: bool)
            ENCODER: callback(encoder_number: int, value: int)
        """
        self.event_callbacks[event_type].append(callback)

    def remove_event_listener(self, event_type: PMPEvent, callback: Callable):
        self.event_callbacks[event_type].remove(callback)

    def _process_midi_message(self, event: tuple[list[int], float], _data):
        midi_message, _delta_time = event
        if len(midi_message) != 3:
            return
        status_byte, data1, data2 = midi_message
        if PITCH_BEND <= status_byte < PITCH_BEND + FADER_COUNT:
            self._handle_fader(status_byte - PITCH_BEND, (data2 << 7) | data1)
        elif status_byte == NOTE_ON and FADER_TOUCH_NOTE <= data1 < FADER_TOUCH_NOTE + FADER_COUNT:
            self._handle_fader_touch(data1 - FADER_TOUCH_NOTE, data2 > 0)
        elif status_byte == NOTE_ON:
            self._handle_button(data1, data2 > 0)
        elif status_byte == CONTROL_CHANGE:
            self._handle_encoder(data1, data2)

    def _handle_fader(self, fader_number: int, value: int):
        normalized_value = value / MAX_FADER_VALUE
        self.fader_positions[fader_number] = min(max(normalized_value, 0.0), 1.0)
        if self.motors_follow_moves:
            self.set_fader(fader_number, normalized_value)
        for callback in self.event_callbacks[PMPEvent.FADER]:
            callback(fader_number, normalized_value)

    def _handle_fader_touch(self, fader_number: int, is_touched: bool):
        self.faders_touched[fader_number] = is_touched
        for callback in self.event_callbacks[PMPEvent.FADER_TOUCH]:
            callback(fader_number, is_touched)

    def _handle_button(self, button_number: int, is_pressed: bool):
        is_lit = self.get_button_light(button_number)
        for callback in self.event_callbacks[PMPEvent.BUTTON]:
            callback(button_number, is_pressed, is_lit)

    def _handle_encoder(self, encoder_number: int, value: int):
        for callback in self.event_callbacks[PMPEvent.ENCODER]:
            callback(encoder_number, value)

    # -- helpers ---------------------------------------------------------------

    def _send(self, message: list[int]):
        try:
            self.midi_out.send_message(message)
        except rtmidi.RtMidiError as error:
            self.connected = False
            raise OSError("Not connected to Platform M+") from error

    @staticmethod
    def _find_port(midi: rtmidi.MidiIn | rtmidi.MidiOut) -> int | None:
        for index, port in enumerate(midi.get_ports()):
            if PORT_NAME in port:
                return index
        return None
