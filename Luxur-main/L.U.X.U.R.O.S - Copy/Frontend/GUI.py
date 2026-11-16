"""Luxur desktop UI.

Obsidian-style graphite surfaces with a holographic HUD core. The UI talks to
the assistant thread only through the small state files in Frontend/Files
(Mic.data, Status.data, Response.data), polled by `StatePoller`.
"""
import math
import sys
import time

from PyQt5.QtCore import QLineF, QObject, QPointF, QRectF, QSize, Qt, QTime, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPen, QPixmap, QRadialGradient,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QScrollArea, QShortcut, QSizeGrip, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from Backend.Common import (
    Assistantname, InputLanguage, Username,
    GetAssistantStatus, GetMicrophoneStatus, GraphicsDirectoryPath, SetMicrophoneStatus, TempDirectoryPath,
)

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
BG = "#121218"          # obsidian base
SURFACE = "#18181f"     # bars
SURFACE_2 = "#22222c"   # raised elements
BORDER = "#2c2c38"
TEXT = "#dcdde3"
MUTED = "#7d7f8c"
VIOLET = "#8b7cf6"      # primary accent
CYAN = "#4fd1ff"        # HUD / listening
AMBER = "#ffb547"       # thinking
RED = "#ff5c6c"         # error / close

STATE_COLORS = {"idle": VIOLET, "listening": CYAN, "thinking": AMBER, "speaking": "#a99bff", "error": RED}
STATE_SPEED = {"idle": 1.0, "listening": 1.6, "thinking": 3.2, "speaking": 1.4, "error": 0.4}


def StateOf(status):
    s = status.strip().lower()
    if s.startswith("listening"):
        return "listening"
    if s.startswith(("thinking", "searching", "translating")):
        return "thinking"
    if s.startswith("answering"):
        return "speaking"
    if s.startswith("error"):
        return "error"
    return "idle"


def SplitStatus(status):
    """'Listening ...' -> ('LISTENING', ''); 'Error: details' -> ('ERROR', 'details')."""
    status = (status or "Available ...").strip()
    if ":" in status:
        label, detail = status.split(":", 1)
        return label.strip().upper(), detail.strip()
    return status.replace("...", "").strip().upper(), ""


def MonoFont(size, bold=False):
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if sys.platform.startswith("win"):
        font.setFamily("Consolas")
    font.setPointSizeF(size)
    font.setBold(bold)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
    return font


_icon_cache = {}


def TintedPixmap(name, color, size):
    """Render one of the white SVG icons in `color` at the screen's pixel density."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (name, color, size, dpr)
    if key not in _icon_cache:
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        QSvgRenderer(str(GraphicsDirectoryPath(f"{name}.svg"))).render(p, QRectF(0, 0, size, size))
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(QRectF(0, 0, size, size), QColor(color))
        p.end()
        _icon_cache[key] = pm
    return _icon_cache[key]


def Icon(name, color=MUTED, checked_color=None, size=18):
    icon = QIcon()
    icon.addPixmap(TintedPixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if checked_color:
        icon.addPixmap(TintedPixmap(name, checked_color, size), QIcon.Normal, QIcon.On)
    return icon


# --------------------------------------------------------------------------
# State polling
# --------------------------------------------------------------------------

class StatePoller(QObject):
    statusChanged = pyqtSignal(str)
    micChanged = pyqtSignal(bool)
    responseChanged = pyqtSignal(str)
    wakeRequested = pyqtSignal()
    restRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = None
        self._mic = None
        self._response = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(100)

    def poll(self):
        status = GetAssistantStatus().strip()
        if status != self._status:
            self._status = status
            self.statusChanged.emit(status)

        mic = GetMicrophoneStatus().strip() == "True"
        if mic != self._mic:
            self._mic = mic
            self.micChanged.emit(mic)

        try:
            if TempDirectoryPath("Wake.data").read_text(encoding="utf-8").strip() == "True":
                TempDirectoryPath("Wake.data").write_text("False", encoding="utf-8")
                self.wakeRequested.emit()
        except (FileNotFoundError, OSError):
            pass

        try:
            if TempDirectoryPath("Rest.data").read_text(encoding="utf-8").strip() == "True":
                TempDirectoryPath("Rest.data").write_text("False", encoding="utf-8")
                self.restRequested.emit()
        except (FileNotFoundError, OSError):
            pass

        try:
            response = TempDirectoryPath("Response.data").read_text(encoding="utf-8")
        except FileNotFoundError:
            response = ""
        if len(response.strip()) > 1 and response != self._response:
            self._response = response
            self.responseChanged.emit(response)

    @staticmethod
    def toggleMic():
        mic_on = GetMicrophoneStatus().strip() == "True"
        if mic_on and GetAssistantStatus().startswith("Answering"):
            # Interrupt playback, but keep the mic on so the assistant loop
            # starts listening again as soon as the speech stops.
            TempDirectoryPath("Interrupt.data").write_text("True", encoding="utf-8")
            return
        SetMicrophoneStatus("False" if mic_on else "True")


# --------------------------------------------------------------------------
# HUD core
# --------------------------------------------------------------------------

class HudCore(QWidget):
    """Animated reactor-style core whose colour and motion follow the assistant state."""

    def __init__(self, parent=None, detailed=True):
        super().__init__(parent)
        self.detailed = detailed
        self.state = "idle"
        self.color = QColor(STATE_COLORS["idle"])
        self.phase = 0.0
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._ticks = {}  # radius -> (minor lines, major lines)
        self._glow = {}   # (rgb, radius) -> pixmap
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def setState(self, state):
        self.state = state

    def showEvent(self, event):
        self._last = time.monotonic()
        self._timer.start(33)  # ~30 fps keeps idle CPU low
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        now = time.monotonic()
        dt, self._last = min(now - self._last, 0.1), now
        self.phase += dt * STATE_SPEED[self.state]
        # Ease the colour towards the target so state changes blend instead of snapping.
        target = QColor(STATE_COLORS[self.state])
        k = min(1.0, dt * 6)
        self.color = QColor(
            int(self.color.red() + (target.red() - self.color.red()) * k),
            int(self.color.green() + (target.green() - self.color.green()) * k),
            int(self.color.blue() + (target.blue() - self.color.blue()) * k),
        )
        self.update()

    def _c(self, alpha):
        c = QColor(self.color)
        c.setAlpha(max(0, min(255, int(alpha))))
        return c

    def _tickLines(self, r):
        key = round(r)
        if key not in self._ticks:
            minor, major = [], []
            for i in range(120):
                a = math.radians(i * 3)
                dx, dy = math.sin(a), -math.cos(a)
                inner = 0.94 if i % 10 == 0 else 0.965
                (major if i % 10 == 0 else minor).append(QLineF(r * dx, r * dy, r * inner * dx, r * inner * dy))
            self._ticks = {key: (minor, major)}
        return self._ticks[key]

    def _drawGlow(self, p, c, r):
        """The ambient glow is the costliest layer, so cache it once the colour has settled."""
        def paint(painter, center):
            glow = QRadialGradient(center, r)
            glow.setColorAt(0.0, self._c(60))
            glow.setColorAt(0.45, self._c(18))
            glow.setColorAt(1.0, self._c(0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, r, r)
            painter.setBrush(Qt.NoBrush)

        if self.color != QColor(STATE_COLORS[self.state]):
            paint(p, c)  # mid-transition: draw live
            return
        key = (self.color.rgb(), round(r))
        if key not in self._glow:
            dpr = self.devicePixelRatioF()
            size = int(math.ceil(r * 2))
            pm = QPixmap(int(size * dpr), int(size * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            paint(painter, QPointF(size / 2, size / 2))
            painter.end()
            if len(self._glow) > 8:
                self._glow.clear()
            self._glow[key] = pm
        pm = self._glow[key]
        p.drawPixmap(QPointF(c.x() - r, c.y() - r), pm)

    @staticmethod
    def _arc(p, center, radius, start_deg, span_deg):
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = min(w, h) / 2 * 0.94
        c = QPointF(w / 2, h / 2)
        t, ph = time.monotonic(), self.phase

        self._drawGlow(p, c, r)

        if self.detailed:
            # Outer tick ring
            minor, major = self._tickLines(r)
            p.save()
            p.translate(c)
            p.rotate(ph * 6)
            p.setPen(QPen(self._c(70), 1))
            p.drawLines(minor)
            p.setPen(QPen(self._c(170), 1.6))
            p.drawLines(major)
            p.restore()

            p.setPen(QPen(self._c(50), 1))
            p.drawEllipse(c, r * 0.87, r * 0.87)

            # Segmented ring
            bright = QPen(self._c(220), max(2.0, r * 0.03), Qt.SolidLine, Qt.FlatCap)
            dim = QPen(self._c(110), max(2.0, r * 0.03), Qt.SolidLine, Qt.FlatCap)
            for i in range(24):
                if i % 6 == 5:
                    continue
                p.setPen(bright if i % 4 == 0 else dim)
                self._arc(p, c, r * 0.78, -ph * 14 + i * 15, 10)

            # Fast inner arcs
            pen = QPen(self._c(200), max(1.5, r * 0.012), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            for start, span, radius, speed in ((0, 110, 0.66, 40), (150, 60, 0.66, 40),
                                               (40, 80, 0.6, -55), (230, 35, 0.6, -55)):
                self._arc(p, c, r * radius, start + ph * speed, span)

            # Inner ring with markers
            p.setPen(QPen(self._c(80), 1))
            p.drawEllipse(c, r * 0.5, r * 0.5)
            p.save()
            p.translate(c)
            p.rotate(-ph * 20)
            p.setPen(Qt.NoPen)
            p.setBrush(self._c(230))
            for _ in range(4):
                p.drawEllipse(QPointF(0, -r * 0.5), r * 0.012 + 1, r * 0.012 + 1)
                p.rotate(90)
            p.restore()
            p.setBrush(Qt.NoBrush)

        core_r = r * (0.24 if self.detailed else 0.42)

        if self.state == "listening":
            for k in range(3):
                f = ((t / 1.6) + k / 3) % 1.0
                p.setPen(QPen(self._c(200 * (1 - f)), 1.5))
                rad = core_r * (1.1 + f * (1.6 if self.detailed else 1.0))
                p.drawEllipse(c, rad, rad)
        elif self.state == "speaking":
            bars = 56 if self.detailed else 24
            p.save()
            p.translate(c)
            p.setPen(QPen(self._c(210), max(1.5, r * 0.01), Qt.SolidLine, Qt.RoundCap))
            for i in range(bars):
                amp = (math.sin(t * 9 + i * 0.7) + math.sin(t * 5.3 + i * 1.9) + 2) / 4
                p.drawLine(QPointF(0, -core_r * 1.15), QPointF(0, -core_r * (1.2 + amp * 0.55)))
                p.rotate(360 / bars)
            p.restore()

        # Core
        pulse = 1 + (0.06 if self.state == "listening" else 0.025) * math.sin(t * 3)
        cr = core_r * pulse
        core = QRadialGradient(c, cr)
        core.setColorAt(0.0, QColor(255, 255, 255, 235))
        core.setColorAt(0.35, self._c(235))
        core.setColorAt(0.75, self._c(90))
        core.setColorAt(1.0, self._c(0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, cr, cr)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._c(200), 1.6))
        p.drawEllipse(c, core_r * 1.08, core_r * 1.08)
        p.end()


class LogoMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(9, 9)
        p.setPen(QPen(QColor(VIOLET), 1.6))
        p.drawEllipse(c, 7.5, 7.5)
        g = QRadialGradient(c, 4)
        g.setColorAt(0, QColor("#ffffff"))
        g.setColorAt(1, QColor(CYAN))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 3.5, 3.5)
        p.end()


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------

class MicButton(QAbstractButton):
    def __init__(self, size=68, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.clicked.connect(StatePoller.toggleMic)
        self.toggled.connect(self._updateTip)
        self._updateTip(False)

    def _updateTip(self, on):
        self.setToolTip("Stop listening (Ctrl+M)" if on else "Start listening (Ctrl+M)")

    def setMic(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._updateTip(on)
        self.update()

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        c = QPointF(s / 2, s / 2)
        r = s / 2 - 3
        on, hover = self.isChecked(), self.underMouse()

        if on:
            glow = QRadialGradient(c, s / 2)
            glow.setColorAt(0.6, QColor(79, 209, 255, 90))
            glow.setColorAt(1.0, QColor(79, 209, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, s / 2, s / 2)
            p.setBrush(QColor(CYAN))
            p.drawEllipse(c, r - 2, r - 2)
        else:
            p.setBrush(QColor(SURFACE_2))
            p.setPen(QPen(QColor(VIOLET if hover else BORDER), 1.5))
            p.drawEllipse(c, r - 2, r - 2)

        icon = int(s * 0.4)
        pm = TintedPixmap("mic" if on else "mic_off", BG if on else (TEXT if hover else MUTED), icon)
        p.drawPixmap(int((s - icon) / 2), int((s - icon) / 2), pm)
        p.end()


class TopBar(QWidget):
    def __init__(self, window, stacked):
        super().__init__(window)
        self.window_ = window
        self.stacked = stacked
        self.setFixedHeight(46)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("TopBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 6, 0)
        layout.setSpacing(0)

        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        bl.addWidget(LogoMark())
        name = QLabel(Assistantname.upper())
        name.setFont(MonoFont(10, bold=True))
        name.setStyleSheet(f"color: {TEXT}; letter-spacing: 4px;")
        bl.addWidget(name)
        version = QLabel("v1 β")
        version.setFont(MonoFont(8))
        version.setStyleSheet(f"color: {MUTED};")
        bl.addWidget(version)
        bl.addStretch(1)

        tabs = QFrame()
        tabs.setObjectName("Tabs")
        tl = QHBoxLayout(tabs)
        tl.setContentsMargins(3, 3, 3, 3)
        tl.setSpacing(2)
        self.group = QButtonGroup(self)
        for index, (label, icon) in enumerate((("Home", "home"), ("Chat", "chat"))):
            button = QPushButton(f" {label}")
            button.setObjectName("Tab")
            button.setCheckable(True)
            button.setIcon(Icon(icon, MUTED, TEXT, 16))
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(f"{label} (Ctrl+{index + 1})")
            self.group.addButton(button, index)
            tl.addWidget(button)
        self.group.button(0).setChecked(True)
        self.group.buttonClicked[int].connect(stacked.setCurrentIndex)
        stacked.currentChanged.connect(lambda i: self.group.button(i).setChecked(True))

        controls = QWidget()
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addStretch(1)
        self.maximize_button = None
        for icon, slot, name in (("minimize", window.showMinimized, "WinButton"),
                                 ("maximize", self.toggleMaximize, "WinButton"),
                                 ("close", window.close, "CloseButton")):
            button = QPushButton()
            button.setObjectName(name)
            button.setIcon(Icon(icon, MUTED, size=14))
            button.setIconSize(QSize(14, 14))
            button.setFixedSize(42, 32)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(slot)
            cl.addWidget(button)
            if icon == "maximize":
                self.maximize_button = button

        layout.addWidget(brand, 1)
        layout.addWidget(tabs, 0, Qt.AlignVCenter)
        layout.addWidget(controls, 1)

    def toggleMaximize(self):
        if self.window_.isMaximized():
            self.window_.showNormal()
        else:
            self.window_.showMaximized()

    def syncMaximizeIcon(self):
        name = "restore" if self.window_.isMaximized() else "maximize"
        self.maximize_button.setIcon(Icon(name, MUTED, size=14))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window_.windowHandle()
            # startSystemMove works on Wayland too, where move() is ignored.
            if handle is None or not handle.startSystemMove():
                self._drag = event.globalPos() - self.window_.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_drag", None) is not None and event.buttons() & Qt.LeftButton:
            self.window_.move(event.globalPos() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        self.toggleMaximize()


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------

class InitialScreen(QWidget):
    HINTS = {
        "idle": "Tap the mic to start a conversation",
        "listening": "Go ahead, I'm listening",
        "thinking": "Working on it",
        "speaking": "Tap the mic to interrupt",
        "error": "Something went wrong, check the console",
    }

    def __init__(self, poller, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.mic_on = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 48)
        layout.setSpacing(0)

        self.hud = HudCore()
        self.hud.setMinimumSize(220, 220)
        self.hud.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.hud, 1)
        layout.addSpacing(18)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setFont(MonoFont(11, bold=True))
        layout.addWidget(self.status)
        layout.addSpacing(6)

        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        layout.addWidget(self.hint)
        layout.addSpacing(22)

        self.mic = MicButton(72)
        layout.addWidget(self.mic, 0, Qt.AlignHCenter)

        poller.statusChanged.connect(self.setStatus)
        poller.micChanged.connect(self.setMic)

        self._backdrop = None
        self._clock = QTimer(self)
        self._clock.timeout.connect(self.update)
        self._clock.start(1000)

    def setStatus(self, status):
        self.state = StateOf(status)
        self.hud.setState(self.state)
        label, detail = SplitStatus(status)
        self.status.setText(label)
        self.status.setStyleSheet(f"color: {STATE_COLORS[self.state]}; letter-spacing: 6px;")
        self.hint.setText(detail or self.HINTS[self.state])
        self.update()

    def setMic(self, on):
        self.mic_on = on
        self.mic.setMic(on)
        self.update()

    def resizeEvent(self, event):
        self._backdrop = None
        super().resizeEvent(event)

    def Backdrop(self):
        """Dot grid, rendered once per size (repainting it every HUD frame is costly)."""
        if self._backdrop is None or self._backdrop.size() != self.size() * self.devicePixelRatioF():
            dpr = self.devicePixelRatioF()
            pm = QPixmap(self.size() * dpr)
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor(BG))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            step = 28
            for x in range(step // 2, self.width(), step):
                for y in range(step // 2, self.height(), step):
                    p.drawEllipse(QPointF(x, y), 1, 1)
            p.end()
            self._backdrop = pm
        return self._backdrop

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.Backdrop())
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # HUD corner brackets
        m, L = 18, 26
        p.setPen(QPen(QColor(VIOLET), 1.5))
        for x, y, dx, dy in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))

        # Telemetry
        p.setFont(MonoFont(8))
        p.setPen(QColor(MUTED))
        pad = 30
        p.drawText(QRectF(pad, pad - 6, 400, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{Assistantname.upper()} // CORE INTERFACE")
        p.drawText(QRectF(w - pad - 400, pad - 6, 400, 20), Qt.AlignRight | Qt.AlignVCenter,
                   QTime.currentTime().toString("HH:mm:ss"))
        p.drawText(QRectF(pad, h - pad - 14, 400, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"VOICE INPUT · {InputLanguage.upper()}")
        p.setPen(QColor(CYAN if self.mic_on else MUTED))
        p.drawText(QRectF(w - pad - 400, h - pad - 14, 400, 20), Qt.AlignRight | Qt.AlignVCenter,
                   "● MIC ARMED" if self.mic_on else "○ MIC STANDBY")
        p.end()


class MessageWidget(QWidget):
    def __init__(self, role, text, stamp=""):
        super().__init__()
        self.role = role
        user = role == "user"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel(f"{(Username if user else Assistantname).upper()}" + (f"  ·  {stamp}" if stamp else ""))
        header.setFont(MonoFont(8, bold=True))
        header.setStyleSheet(f"color: {VIOLET if user else CYAN};")
        header.setAlignment(Qt.AlignRight if user else Qt.AlignLeft)
        layout.addWidget(header)

        self.body = QLabel(text)
        self.body.setTextFormat(Qt.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setCursor(Qt.IBeamCursor)
        self.body.setObjectName("UserBubble" if user else "AssistantNote")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if user:
            row.addStretch(1)
            row.addWidget(self.body)
        else:
            accent = QFrame()
            accent.setFixedWidth(2)
            accent.setStyleSheet(f"background: {CYAN}; border: none;")
            row.setSpacing(14)
            row.addWidget(accent)
            row.addWidget(self.body, 1)
        layout.addLayout(row)

    def fitWidth(self, column_width):
        """Size user bubbles to their text, capped at 78% of the column."""
        if self.role != "user" or column_width <= 0:
            return
        self.body.ensurePolished()
        self.body.setWordWrap(False)
        natural = self.body.sizeHint().width()  # single-line width incl. stylesheet padding
        self.body.setWordWrap(True)
        self.body.setFixedWidth(min(int(column_width * 0.78), natural + 2))


class ChatSection(QWidget):
    def __init__(self, poller, parent=None):
        super().__init__(parent)
        self.messages = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        canvas = QWidget()
        canvas.setObjectName("ChatCanvas")
        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.addStretch(1)
        self.column = QWidget()
        self.column.setMaximumWidth(820)
        self.column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.list = QVBoxLayout(self.column)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(22)
        self.list.addStretch(1)
        outer.addWidget(self.column, 100)
        outer.addStretch(1)
        self.scroll.setWidget(canvas)
        layout.addWidget(self.scroll, 1)

        self.empty = QLabel("No messages yet. Switch the mic on and say hello.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        self.list.insertWidget(0, self.empty)

        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _min, _max: bar.setValue(_max))

        # Bottom status bar
        footer = QFrame()
        footer.setObjectName("Footer")
        footer.setFixedHeight(76)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(14)
        self.hud = HudCore(detailed=False)
        self.hud.setFixedSize(44, 44)
        fl.addWidget(self.hud)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.status = QLabel()
        self.status.setFont(MonoFont(9, bold=True))
        self.hint = QLabel(f"Voice transcript with {Assistantname}")
        self.hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        text.addStretch(1)
        text.addWidget(self.status)
        text.addWidget(self.hint)
        text.addStretch(1)
        fl.addLayout(text, 1)
        self.mic = MicButton(52)
        fl.addWidget(self.mic)
        layout.addWidget(footer)

        poller.responseChanged.connect(self.loadMessages)
        poller.statusChanged.connect(self.setStatus)
        poller.micChanged.connect(self.mic.setMic)

    def setStatus(self, status):
        state = StateOf(status)
        self.hud.setState(state)
        label, detail = SplitStatus(status)
        self.status.setText(label)
        self.status.setStyleSheet(f"color: {STATE_COLORS[state]}; letter-spacing: 4px;")
        self.hint.setText(detail or f"Voice transcript with {Assistantname}")

    @staticmethod
    def ParseMessages(text):
        """Split 'Name : message' blocks into (role, text) pairs; continuation lines join the previous one."""
        prefixes = (("user", f"{Username} :"), ("assistant", f"{Assistantname} :"))
        result = []
        for line in text.split("\n"):
            for role, prefix in prefixes:
                if line.startswith(prefix):
                    result.append([role, line[len(prefix):].strip()])
                    break
            else:
                if result:
                    result[-1][1] += "\n" + line
                elif line.strip():
                    result.append(["assistant", line.strip()])
        return [(role, body.strip()) for role, body in result if body.strip()]

    def loadMessages(self, text):
        stamp = QTime.currentTime().toString("HH:mm") if self.messages else ""
        for role, body in self.ParseMessages(text):
            self.addMessage(role, body, stamp)

    def addMessage(self, role, text, stamp=""):
        self.empty.hide()
        widget = MessageWidget(role, text, stamp)
        widget.fitWidth(self.column.width())
        self.list.insertWidget(self.list.count() - 1, widget)
        self.messages.append(widget)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for widget in self.messages:
            widget.fitWidth(self.column.width())



# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------

STYLESHEET = f"""
QWidget {{ color: {TEXT}; font-size: 14px; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
#Root {{ background: {BG}; border: 1px solid {BORDER}; }}
#TopBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
#Tabs {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; }}
#Tab {{ background: transparent; color: {MUTED}; border: none; border-radius: 6px;
        padding: 5px 16px; font-size: 13px; }}
#Tab:hover {{ color: {TEXT}; }}
#Tab:checked {{ background: {SURFACE_2}; color: {TEXT}; }}
#WinButton, #CloseButton {{ background: transparent; border: none; border-radius: 6px; }}
#WinButton:hover {{ background: {SURFACE_2}; }}
#CloseButton:hover {{ background: {RED}; }}
#ChatCanvas {{ background: {BG}; }}
#Footer {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
#UserBubble {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px;
               padding: 10px 14px; font-size: 14px; }}
#AssistantNote {{ padding: 2px 0; font-size: 14px; }}
QScrollArea {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {VIOLET}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setWindowTitle(Assistantname)
        self.setWindowIcon(QIcon(str(GraphicsDirectoryPath("jarvis_animated.gif"))))
        self.setMinimumSize(760, 540)

        self.poller = StatePoller(self)
        self.poller.wakeRequested.connect(self.wakeUp)
        self.poller.restRequested.connect(self.restNow)
        root = QWidget()
        root.setObjectName("Root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.stacked = QStackedWidget()
        self.stacked.addWidget(InitialScreen(self.poller))
        self.stacked.addWidget(ChatSection(self.poller))
        self.top_bar = TopBar(self, self.stacked)
        layout.addWidget(self.top_bar)
        layout.addWidget(self.stacked, 1)
        self.setCentralWidget(root)

        self.grip = QSizeGrip(root)
        self.grip.setFixedSize(16, 16)
        self.grip.setStyleSheet("background: transparent;")

        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.stacked.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.stacked.setCurrentIndex(1))
        QShortcut(QKeySequence("Ctrl+M"), self, StatePoller.toggleMic)

        available = QApplication.primaryScreen().availableGeometry()
        width = min(1280, int(available.width() * 0.9))
        height = min(820, int(available.height() * 0.9))
        self.resize(width, height)
        self.move(available.center().x() - width // 2, available.center().y() - height // 2)
        self.poller.poll()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.grip.move(self.width() - self.grip.width() - 2, self.height() - self.grip.height() - 2)
        self.grip.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.WindowStateChange:
            self.top_bar.syncMaximizeIcon()
            self.grip.setVisible(not self.isMaximized())
            try:
                TempDirectoryPath("Minimized.data").write_text(
                    "True" if self.isMinimized() else "False", encoding="utf-8")
            except OSError:
                pass

    def wakeUp(self):
        # Called (via the poller) when the wake listener hears "LUXUR",
        # "wake up", or detects three claps while minimized.
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def restNow(self):
        # Luxur heard "rest": stop listening and minimize. The wake listener
        # brings the window back on "LUXUR" / "wake up" / three claps.
        SetMicrophoneStatus("False")
        self.showMinimized()


def GraphicalUserInterface():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    GraphicalUserInterface()
