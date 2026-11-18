"""Native Qt controls for the connected Hammerhead earbuds."""

from pathlib import Path
import os
import stat
import sys

from PyQt6.QtCore import QLockFile, QObject, QStandardPaths, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QIcon, QPalette
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .device import Controller, DeviceError


NOISE_MODES = {"anc": "Noise cancelling", "ambient": "Ambient", "off": "Off"}
ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "hammerhead-control.svg"


class DeviceWorker(QObject):
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.controller = None

    @pyqtSlot(str, str)
    def perform(self, operation, value):
        try:
            if self.controller is None:
                self.controller = Controller()
            if operation == "status":
                status = self.controller.status()
            elif operation == "noise":
                status = self.controller.set_noise_mode(value)
            elif operation == "source":
                status = self.controller.set_source(value)
            elif operation == "pairing":
                status = self.controller.start_pairing()
            else:
                raise ValueError(f"Unknown operation: {operation}")
            self.completed.emit(status)
        except DeviceError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"Unable to communicate with the earbuds: {error}")


class ControlWindow(QWidget):
    requested = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("hammerheadWindow")
        self.setWindowTitle("Hammerhead Control")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumWidth(470)
        self.resize(500, 480)
        self._status = {
            "connected": False, "accessible": False, "detail": "Looking for your earbuds…",
            "noise_mode": None, "capabilities": [],
        }
        self._busy = False
        self._request_user_action = False
        self._closing = False
        self._thread_stopped = False
        self._noise_buttons = {}
        self._noise_actions = {}
        self._build_window()
        self._build_tray()

        self._thread = QThread(self)
        self._worker = DeviceWorker()
        self._worker.moveToThread(self._thread)
        self.requested.connect(self._worker.perform)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._shutdown_finished)
        self._thread.start()

        self._poll = QTimer(self)
        self._poll.setInterval(5000)
        self._poll.timeout.connect(lambda: self.request("status", user_action=False))
        self._poll.start()
        self._render()
        QTimer.singleShot(0, lambda: self.request("status", user_action=False))

    def _label(self, text, name, muted=False):
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        if muted:
            palette = label.palette()
            foreground = palette.color(QPalette.ColorRole.WindowText)
            background = palette.color(QPalette.ColorRole.Window)
            palette.setColor(QPalette.ColorRole.WindowText, QColor(*[
                round(0.75 * fore + 0.25 * back)
                for fore, back in zip(foreground.getRgb()[:3], background.getRgb()[:3])
            ]))
            label.setPalette(palette)
        return label

    def _build_window(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(48, 48))
        icon.setFixedSize(48, 48)
        header.addWidget(icon)
        titles = QVBoxLayout()
        title = self._label("Hammerhead Control", "titleLabel")
        font = title.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        title.setFont(font)
        titles.addWidget(title)
        titles.addWidget(self._label("Razer Hammerhead V3 HyperSpeed", "modelLabel", True))
        header.addLayout(titles, 1)
        layout.addLayout(header)

        status_row = QHBoxLayout()
        self.connection_label = self._label("Checking connection…", "connectionLabel")
        font = self.connection_label.font()
        font.setBold(True)
        self.connection_label.setFont(font)
        status_row.addWidget(self.connection_label, 1)
        self.battery_label = self._label("", "batteryLabel")
        status_row.addWidget(self.battery_label)
        layout.addLayout(status_row)
        self.detail_label = self._label("", "detailLabel")
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_label)

        noise_group = QGroupBox("Listening mode")
        noise_layout = QVBoxLayout(noise_group)
        self.mode_label = self._label("Current mode: Unknown", "modeLabel")
        noise_layout.addWidget(self.mode_label)
        mode_row = QHBoxLayout()
        for mode, label in NOISE_MODES.items():
            button = QPushButton(label)
            button.setObjectName(f"noise_{mode}")
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, mode=mode: self.request("noise", mode))
            mode_row.addWidget(button)
            self._noise_buttons[mode] = button
        noise_layout.addLayout(mode_row)
        self.noise_hint = self._label("", "noiseHint", True)
        noise_layout.addWidget(self.noise_hint)
        layout.addWidget(noise_group)

        source_group = QGroupBox("Connection")
        source_layout = QVBoxLayout(source_group)
        self.source_button = QPushButton("Switch Bluetooth / HyperSpeed")
        self.source_button.setObjectName("source_toggle")
        self.source_button.clicked.connect(lambda: self.request("source", "toggle"))
        source_layout.addWidget(self.source_button)
        self.source_hint = self._label("", "sourceHint", True)
        source_layout.addWidget(self.source_hint)
        self.pairing_button = QPushButton("Start Bluetooth pairing")
        self.pairing_button.setObjectName("pairingButton")
        self.pairing_button.clicked.connect(lambda: self.request("pairing"))
        source_layout.addWidget(self.pairing_button)
        self.pairing_hint = self._label("", "pairingHint", True)
        source_layout.addWidget(self.pairing_hint)
        layout.addWidget(source_group)

        self.error_label = self._label("", "errorLabel")
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.setAccessibleName("Device error")
        layout.addWidget(self.error_label)
        layout.addStretch(1)

        footer = QHBoxLayout()
        self.activity_label = self._label("", "activityLabel", True)
        footer.addWidget(self.activity_label, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.clicked.connect(lambda: self.request("status"))
        footer.addWidget(self.refresh_button)
        self.tray_button = QPushButton("Hide to tray")
        self.tray_button.setObjectName("hideToTrayButton")
        self.tray_button.clicked.connect(self.hide)
        footer.addWidget(self.tray_button)
        layout.addLayout(footer)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Hammerhead Control")
        self.tray_menu = QMenu(self)
        show_action = self.tray_menu.addAction("Show controls")
        show_action.triggered.connect(self.show_controls)
        self.tray_menu.addSeparator()
        for mode, label in NOISE_MODES.items():
            action = QAction(label, self)
            action.setObjectName(f"tray_noise_{mode}")
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, mode=mode: self.request("noise", mode))
            self.tray_menu.addAction(action)
            self._noise_actions[mode] = action
        self.source_action = self.tray_menu.addAction("Switch Bluetooth / HyperSpeed")
        self.source_action.setObjectName("tray_source_toggle")
        self.source_action.triggered.connect(lambda: self.request("source", "toggle"))
        self.pairing_action = self.tray_menu.addAction("Start Bluetooth pairing")
        self.pairing_action.setObjectName("trayPairingAction")
        self.pairing_action.triggered.connect(lambda: self.request("pairing"))
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Quit").triggered.connect(self.close)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def show_controls(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_controls()

    def request(self, operation, value="", user_action=True):
        if self._busy or self._closing:
            self._render()
            return
        if operation != "status":
            ready = self._status["connected"] and self._status["accessible"]
            if not ready or operation not in self._status["capabilities"]:
                self._render()
                return
        if user_action:
            self.error_label.clear()
        self._request_user_action = user_action
        self._busy = True
        self.activity_label.setText("Refreshing…" if operation == "status" else "Applying…")
        self._render()
        self.requested.emit(operation, value)

    @pyqtSlot(dict)
    def _completed(self, status):
        self._status = status
        self._finish_request()

    @pyqtSlot(str)
    def _failed(self, message):
        self.error_label.setText(f"Could not complete the request.\n{message}")
        self._status = {
            "connected": False, "accessible": False,
            "detail": "Device status could not be confirmed. Refresh to try again.",
            "noise_mode": None, "capabilities": [],
        }
        if self._request_user_action and not self.isVisible() and not self._closing:
            self.tray.showMessage("Hammerhead Control", message,
                                  QSystemTrayIcon.MessageIcon.Warning)
        self._finish_request()

    def _finish_request(self):
        self._busy = False
        self.activity_label.clear()
        self._render()
        if self._closing:
            self._thread.quit()

    def _render(self):
        status = self._status
        ready = status["connected"] and status["accessible"]
        enabled = ready and not self._busy and not self._closing
        capabilities = status["capabilities"]
        if status["connected"]:
            connection = "Connected" if status["accessible"] else "Device access needed"
        else:
            connection = "Not connected"
        self.connection_label.setText(connection)
        self.detail_label.setText(status["detail"])
        self.detail_label.setVisible(bool(status["detail"]))
        battery = status.get("battery")
        self.battery_label.setText(f"Battery {battery}%" if battery is not None else "")
        noise_mode = status["noise_mode"] if ready else None
        mode_name = NOISE_MODES.get(noise_mode, "Unknown")
        self.mode_label.setText(f"Current mode: {mode_name}")
        self.tray.setToolTip(f"Hammerhead Control\n{connection} · {mode_name}")
        for mode, button in self._noise_buttons.items():
            button.setEnabled(enabled and "noise" in capabilities)
            button.setChecked(noise_mode == mode)
            self._noise_actions[mode].setEnabled(button.isEnabled())
            self._noise_actions[mode].setChecked(noise_mode == mode)
        self.source_button.setEnabled(enabled and "source" in capabilities)
        self.source_action.setEnabled(self.source_button.isEnabled())
        self.noise_hint.setText("" if "noise" in capabilities else
                                "Listening-mode controls are not available for this connection.")
        self.noise_hint.setVisible(bool(self.noise_hint.text()))
        self.source_hint.setText("Switching to Bluetooth disconnects computer controls. "
                                 "Use the earbud gesture to return to HyperSpeed."
                                 if "source" in capabilities else
                                 "Switching audio sources from this computer is not available.")
        self.pairing_button.setEnabled(enabled and "pairing" in capabilities)
        self.pairing_button.setVisible("pairing" in capabilities)
        self.pairing_action.setEnabled(self.pairing_button.isEnabled())
        self.pairing_action.setVisible("pairing" in capabilities)
        self.pairing_hint.setText("Make the earbuds discoverable to a new Bluetooth device."
                                  if "pairing" in capabilities else
                                  "To pair a new Bluetooth device, triple tap an earbud and hold "
                                  "the last tap for 3 seconds. Computer pairing control is unavailable.")
        self.error_label.setVisible(bool(self.error_label.text()))
        self.refresh_button.setEnabled(not self._busy and not self._closing)
        self.tray_button.setEnabled(QSystemTrayIcon.isSystemTrayAvailable() and not self._closing)

    def closeEvent(self, event: QCloseEvent):
        if self._thread_stopped:
            self.tray.hide()
            event.accept()
            QApplication.instance().quit()
            return
        event.ignore()
        self._closing = True
        self._poll.stop()
        self.activity_label.setText("Closing…")
        self._render()
        if not self._busy:
            self._thread.quit()

    def _shutdown_finished(self):
        self._thread_stopped = True
        self.close()


def run_gui() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Hammerhead Control")
    app.setOrganizationName("Hammerhead Control")
    app.setDesktopFileName("hammerhead-control")
    app.setQuitOnLastWindowClosed(False)
    runtime = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation))
    socket_path = runtime / "hammerhead-control.sock"
    lock = QLockFile(str(runtime / "hammerhead-control.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        # The existing process may still be setting up its server.
        for _ in range(20):
            peer = QLocalSocket()
            peer.connectToServer(str(socket_path))
            if peer.waitForConnected(100):
                peer.disconnectFromServer()
                return 0
            QThread.msleep(50)
        QMessageBox.warning(None, "Hammerhead Control",
                            "Hammerhead Control is already running but did not respond.")
        return 1

    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    try:
        # The lock proves no other application instance owns this socket.
        # A crashed instance can leave its Unix socket behind.
        try:
            previous_socket = socket_path.lstat()
        except FileNotFoundError:
            previous_socket = None
        if previous_socket is not None:
            if not stat.S_ISSOCK(previous_socket.st_mode) or previous_socket.st_uid != os.getuid():
                raise RuntimeError(f"Cannot use the application socket: {socket_path}")
            QLocalServer.removeServer(str(socket_path))
        if not server.listen(str(socket_path)):
            raise RuntimeError(server.errorString())
    except RuntimeError as error:
        lock.unlock()
        QMessageBox.critical(None, "Hammerhead Control", str(error))
        return 1

    window = ControlWindow()

    def activate_window():
        while server.hasPendingConnections():
            peer = server.nextPendingConnection()
            peer.disconnectFromServer()
            peer.deleteLater()
        window.show_controls()

    server.newConnection.connect(activate_window)
    window.show()
    try:
        return app.exec()
    finally:
        window._poll.stop()
        window._thread.quit()
        window._thread.wait()
        server.close()
        lock.unlock()
