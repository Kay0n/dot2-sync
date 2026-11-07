"""Data types and errors shared by the dot2 package"""

from dataclasses import dataclass
from enum import IntEnum


class ExecutorKind(IntEnum):
    # Values are the console's `itemsType` codes
    FADER = 2
    BUTTON = 3


@dataclass(frozen=True)
class ExecutorGroup:
    """A range of executors to watch, numbered as on the console"""

    kind: ExecutorKind
    first: int
    count: int


@dataclass(frozen=True)
class Executor:
    """The state of one executor, as last reported by the console"""

    number: int
    kind: ExecutorKind
    active: bool
    position: float = 0.0  # faders only, 0.0-1.0


class Dot2Error(Exception):
    """Connecting to or talking to the console failed"""


class AuthenticationError(Dot2Error):
    """The console rejected the password"""
