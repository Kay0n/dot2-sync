"""Start on login: a Run registry value on Windows, an XDG .desktop file elsewhere"""

import contextlib
import os
import sys
from pathlib import Path

from config import APP_NAME


def launch_command() -> str:
    """Starts this copy of the app without a console window"""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return f'"{sys.executable}"'
    python = Path(sys.executable)
    if sys.platform == "win32" and (pythonw := python.with_name("pythonw.exe")).exists():
        python = pythonw
    return f'"{python}" "{Path(__file__).resolve().with_name("main.py")}"'


def update_path():
    """In case this build moved. Runs from source leave the entry alone"""
    if getattr(sys, "frozen", False) and is_enabled():
        enable()


if sys.platform == "win32":
    import winreg

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def is_enabled() -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
        except FileNotFoundError:
            return False
        return True

    def enable():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())

    def disable():
        with contextlib.suppress(FileNotFoundError):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_NAME)

else:
    DESKTOP_FILE = (
        Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / f"{APP_NAME}.desktop"
    )

    def is_enabled() -> bool:
        return DESKTOP_FILE.exists()

    def enable():
        DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=dot2 Sync\n"
            f"Exec={launch_command()}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

    def disable():
        DESKTOP_FILE.unlink(missing_ok=True)
