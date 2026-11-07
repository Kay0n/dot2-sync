"""Async client for the grandMA2 dot2 web remote

    groups = [
        ExecutorGroup(ExecutorKind.FADER, first=1, count=15),
        ExecutorGroup(ExecutorKind.BUTTON, first=101, count=14),
    ]
    async with Dot2Client("192.168.1.20", "password", groups) as dot2:
        dot2.add_listener(print)
        await dot2.set_fader(1, 0.5)
"""

from .client import Dot2Client
from .models import AuthenticationError, Dot2Error, Executor, ExecutorGroup, ExecutorKind

__all__ = ["Dot2Client", "Executor", "ExecutorGroup", "ExecutorKind", "Dot2Error", "AuthenticationError"]
