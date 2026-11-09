import asyncio
import logging
import sys
from collections.abc import Callable

import qasync
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import autostart
from config import APP_NAME, VERSION, Config, log_path
from sync import DeviceStatus, Dot2PMPSync

log = logging.getLogger(__name__)

TITLE = "dot2 Sync"
GREEN = QColor("#2ecc71")
AMBER = QColor("#f39c12")
RED = QColor("#e74c3c")


def dot_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(4, 4, 56, 56)
    painter.end()
    return QIcon(pixmap)


def overall_status(sync: Dot2PMPSync) -> tuple[QColor, str]:
    """Returns a colour and a short description"""
    if sync.syncing:
        return GREEN, "Sync active"
    if sync.pmp_status.connected:
        return AMBER, "Waiting for dot2"
    if sync.dot2_status.connected:
        return AMBER, "Waiting for Platform M+"
    return RED, "Not connected"


class DeviceRow(QWidget):
    """A coloured dot, the device name and its connection state"""

    def __init__(self, name: str):
        super().__init__()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.state_label = QLabel()
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.state_label.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.dot)
        layout.addWidget(QLabel(f"<b>{name}</b>"))
        layout.addWidget(self.state_label, stretch=1)

    def show_status(self, status: DeviceStatus):
        color = GREEN if status.connected else RED
        self.dot.setStyleSheet(f"background: {color.name()}; border-radius: 6px;")
        self.state_label.setText(str(status))


class StatusWindow(QWidget):
    def __init__(self, sync: Dot2PMPSync, config: Config, on_quit: Callable[[], None]):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.sync = sync
        self.config = config
        self.setWindowTitle(TITLE)
        self.setFixedWidth(340)

        self.pmp_row = DeviceRow("Platform M+")
        self.dot2_row = DeviceRow("dot2")
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(self.summary_label.font())
        font.setPointSizeF(font.pointSizeF() * 1.3)
        font.setBold(True)
        self.summary_label.setFont(font)

        self.host_input = QLineEdit(config.dot2_host)
        self.password_input = QLineEdit(config.dot2_password)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.save_button = QPushButton("Save")
        self.save_button.setEnabled(False)
        self.host_input.textChanged.connect(self._update_save_button)
        self.password_input.textChanged.connect(self._update_save_button)
        self.host_input.returnPressed.connect(self._save_settings)
        self.password_input.returnPressed.connect(self._save_settings)
        self.save_button.clicked.connect(self._save_settings)

        self.start_on_login = QCheckBox("Start with Windows" if sys.platform == "win32" else "Start on login")
        self.start_on_login.setChecked(autostart.is_enabled())
        self.start_on_login.toggled.connect(self._set_autostart)

        open_log = QPushButton("Open log")
        open_log.setFlat(True)
        open_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path()))))
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Try to reconnect now")
        refresh.clicked.connect(sync.retry_connections)
        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(on_quit)

        settings = QFormLayout()
        settings.addRow("dot2 IP", self.host_input)
        settings.addRow("Password", self.password_input)
        save_row = QHBoxLayout()
        save_row.addWidget(self.start_on_login)
        save_row.addStretch()
        save_row.addWidget(self.save_button)

        version = QLabel(f"v{VERSION}")
        version.setEnabled(False)  # greyed out

        buttons = QHBoxLayout()
        buttons.addWidget(open_log)
        buttons.addWidget(version)
        buttons.addStretch()
        buttons.addWidget(refresh)
        buttons.addWidget(quit_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pmp_row)
        layout.addWidget(self.dot2_row)
        layout.addWidget(separator())
        layout.addWidget(self.summary_label)
        layout.addWidget(separator())
        layout.addLayout(settings)
        layout.addLayout(save_row)
        layout.addWidget(separator())
        layout.addLayout(buttons)

    def show_status(self):
        self.pmp_row.show_status(self.sync.pmp_status)
        self.dot2_row.show_status(self.sync.dot2_status)
        color, text = overall_status(self.sync)
        self.summary_label.setText(text)
        self.summary_label.setStyleSheet(f"color: {color.name()};")

    def show_near_tray(self):
        """Show in the bottom-right corner, near the tray"""
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        margin = 12
        self.move(area.right() - self.width() - margin, area.bottom() - self.height() - margin)
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show_near_tray()

    def closeEvent(self, event):
        event.ignore()  # keep running in the tray
        self.hide()

    def _update_save_button(self):
        changed = (self.host_input.text().strip(), self.password_input.text()) != (self.config.dot2_host, self.config.dot2_password)
        self.save_button.setEnabled(changed and bool(self.host_input.text().strip()))

    def _save_settings(self):
        if not self.save_button.isEnabled():
            return
        self.config.dot2_host = self.host_input.text().strip()
        self.config.dot2_password = self.password_input.text()
        try:
            self.config.save()
        except OSError as error:
            QMessageBox.warning(self, TITLE, f"Could not save settings:\n{error}")
        self.sync.update_dot2_settings(self.config.dot2_host, self.config.dot2_password)
        self.save_button.setEnabled(False)

    def _set_autostart(self, enabled: bool):
        try:
            autostart.enable() if enabled else autostart.disable()
        except OSError as error:
            QMessageBox.warning(self, TITLE, f"Could not change the start-up setting:\n{error}")
        self.start_on_login.blockSignals(True)
        self.start_on_login.setChecked(autostart.is_enabled())
        self.start_on_login.blockSignals(False)


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class Tray:
    def __init__(self, sync: Dot2PMPSync, config: Config, on_quit: Callable[[], None]):
        self.sync = sync
        self.window = StatusWindow(sync, config, on_quit)

        menu = QMenu()
        menu.addAction(QAction("Open", menu, triggered=self.window.show_near_tray))
        menu.addAction(QAction("Refresh", menu, triggered=sync.retry_connections))
        menu.addSeparator()
        menu.addAction(QAction("Quit", menu, triggered=on_quit))
        self.menu = menu  # the tray icon doesn't keep it alive

        self.icon = QSystemTrayIcon()
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)

        sync.add_status_listener(self.show_status)
        self.show_status()
        self.icon.show()
        # At Windows login the tray may not exist yet; Qt adds the icon once it does
        if sys.platform != "win32" and not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("No system tray available, showing the window instead")
            self.window.show_near_tray()

    def show_status(self):
        color, text = overall_status(self.sync)
        icon = dot_icon(color)
        self.icon.setIcon(icon)
        self.icon.setToolTip(f"{TITLE}: {text}")
        self.window.setWindowIcon(icon)
        self.window.show_status()

    def hide(self):
        self.icon.hide()
        self.window.hide()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason is QSystemTrayIcon.ActivationReason.Trigger:  # left click
            self.window.toggle()


# -- single instance -------------------------------------------------------


def show_running_instance() -> bool:
    """If the app is already running, make it show its window and return True"""
    socket = QLocalSocket()
    socket.connectToServer(APP_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.disconnectFromServer()
    return True


def listen_for_new_instances(show: Callable[[], None]) -> QLocalServer:
    """Call `show()` whenever another copy of the app is started"""
    QLocalServer.removeServer(APP_NAME)  # clears a stale socket after a crash
    server = QLocalServer()
    if not server.listen(APP_NAME):
        log.warning("Could not listen for other instances: %s", server.errorString())

    def new_connection():
        while connection := server.nextPendingConnection():
            connection.deleteLater()
        show()

    server.newConnection.connect(new_connection)
    return server


# -- running ---------------------------------------------------------------


def run(sync: Dot2PMPSync, config: Config) -> int:
    """Run the tray app until the user quits. Returns the exit code"""
    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    app.setQuitOnLastWindowClosed(False)
    if show_running_instance():
        log.info("Already running, showing that copy instead")
        return 0
    return asyncio.run(_run(app, sync, config), loop_factory=qasync.QEventLoop)


async def _run(app: QApplication, sync: Dot2PMPSync, config: Config) -> int:
    quit_requested = asyncio.Event()
    app.aboutToQuit.connect(quit_requested.set)  # e.g. Windows logging off
    tray = Tray(sync, config, quit_requested.set)
    server = listen_for_new_instances(tray.window.show_near_tray)

    sync_task = asyncio.create_task(sync.run())
    quit_task = asyncio.create_task(quit_requested.wait())
    await asyncio.wait([sync_task, quit_task], return_when=asyncio.FIRST_COMPLETED)

    log.info("Quitting")
    tray.hide()
    server.close()
    quit_task.cancel()
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        return 0
    except Exception:
        log.exception("Sync stopped unexpectedly")
        return 1
    return 0
