from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "dot2-sync"
VERSION = "1.0.0"

log = logging.getLogger(__name__)


def config_dir() -> Path:
    """%APPDATA%\\dot2-sync on Windows, ~/.config/dot2-sync elsewhere"""
    if sys.platform == "win32":
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def log_path() -> Path:
    return config_dir() / f"{APP_NAME}.log"


@dataclass
class Config:
    dot2_host: str = "127.0.0.1"
    dot2_password: str = "password"

    @staticmethod
    def path() -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> Config:
        """Load the saved settings, or the defaults if there aren't any"""
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("Could not read %s, using defaults", cls.path())
            return cls()
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def save(self):
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
