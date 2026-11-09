from __future__ import annotations

import json
import logging
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def _read_pyproject() -> dict:
    """pyproject.toml, which the build bundles next to the exe"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    with open(root / "pyproject.toml", "rb") as file:
        return tomllib.load(file)


_pyproject = _read_pyproject()
APP_NAME: str = _pyproject["project"]["name"]
VERSION: str = _pyproject["project"]["version"]
DESCRIPTION: str = _pyproject["project"]["description"]
DISPLAY_NAME: str = _pyproject["tool"]["dot2-sync"]["display-name"]

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
        """Load saved settings or defaults if empty"""
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
