"""Message formats of the dot2 web remote. Connection.send adds the session id"""

from typing import Any

from .models import Executor, ExecutorGroup, ExecutorKind

Message = dict[str, Any]

_KINDS = {kind.value: kind for kind in ExecutorKind}


def login(password_md5: str) -> Message:
    return {"requestType": "login", "username": "remote", "password": password_md5}


def close() -> Message:
    return {"requestType": "close"}


def command(text: str) -> Message:
    return {"requestType": "command", "command": text}


def playbacks_request(groups: list[ExecutorGroup]) -> Message:
    # The view settings mirror what the console's own web remote sends
    return {
        "requestType": "playbacks",
        "startIndex": [group.first - 1 for group in groups],
        "itemsCount": [group.count for group in groups],
        "itemsType": [group.kind.value for group in groups],
        "pageIndex": 0,
        "view": 2,
        "execButtonViewMode": 1,
        "buttonsViewMode": 0,
        "maxRequests": 1,
    }


def is_login_reply(message: Message) -> bool:
    return message.get("responseType") == "login"


def is_playbacks(message: Message) -> bool:
    return message.get("responseType") == "playbacks"


def parse_playbacks(message: Message) -> list[Executor]:
    """Turn a playbacks response into Executors, numbered as on the console"""
    executors = []
    for group in message.get("itemGroups", []):
        kind = _KINDS.get(group.get("itemsType"))
        if kind is None:
            continue
        for row in group.get("items", []):
            executors.extend(_parse_executor(item, kind) for item in row)
    return executors


def _parse_executor(item: Message, kind: ExecutorKind) -> Executor:
    return Executor(
        number=item["iExec"] + 1,  # the console counts from 0
        kind=kind,
        active=item.get("isRun") == 1,
        position=_fader_position(item) if kind is ExecutorKind.FADER else 0.0,
    )


def _fader_position(item: Message) -> float:
    for block in item.get("executorBlocks", []):
        if "fader" in block:
            return float(block["fader"].get("v", 0.0))
    return 0.0
