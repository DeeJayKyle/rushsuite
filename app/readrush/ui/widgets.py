"""Reusable ReadRush widgets."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme as T

AUDIO_FILTER = ("Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma *.aiff *.aif *.mp4);;All files (*)")


class Relay(QObject):
    """Receives worker signals in the GUI thread."""

    def __init__(self, owner, on_done, on_fail, on_progress):
        super().__init__()
        self.owner, self.cb_done, self.cb_fail, self.cb_prog = owner, on_done, on_fail, on_progress

    @Slot(float, str)
    def prog(self, f, m):
        if self.cb_prog:
            self.cb_prog(f, m)

    @Slot(object)
    def ok(self, res):
        if self.cb_done:
            self.cb_done(res)

    @Slot(str)
    def fail(self, msg):
        (self.cb_fail or (lambda m: error_box(self.owner, m)))(msg)

    @Slot()
    def cleanup(self):
        jobs = self.owner.__dict__.get("_bg_jobs", [])
        for j in list(jobs):
            if j[2] is self:
                jobs.remove(j)


class _Worker(QObject):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, args, kwargs, wants_progress):
        super().__init__()
        self.fn, self.args, self.kwargs, self.wp = fn, args, kwargs, wants_progress

    def run(self):
        import traceback
        try:
            kw = dict(self.kwargs)
            if self.wp:
                kw["progress"] = lambda f, m: self.progress.emit(float(f), str(m))
            self.done.emit(self.fn(*self.args, **kw))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


def run_bg(owner, fn, *args, on_done=None, on_fail=None, on_progress=None, progress_kw=True, **kwargs):
    """Run fn in a background QThread. Callbacks run in the GUI thread. If on_progress is given (and
    progress_kw), fn receives progress=callback(fraction, message)."""
    thread = QThread()
    worker = _Worker(fn, args, kwargs, wants_progress=bool(on_progress) and progress_kw)
    relay = Relay(owner, on_done, on_fail, on_progress)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(relay.prog)
    worker.done.connect(relay.ok)
    worker.failed.connect(relay.fail)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(relay.cleanup)
    owner.__dict__.setdefault("_bg_jobs", []).append((thread, worker, relay))
    thread.start()
    return worker


class Busy(QFrame):
    """Inline progress line: label + thin bar."""

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.label = label("", "faint")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        v.addWidget(self.label)
        v.addWidget(self.bar)
        self.hide()

    def start(self, msg="Working…"):
        self.label.setText(msg)
        self.bar.setValue(0)
        self.show()

    def update_(self, f, m):
        self.bar.setValue(int(f * 1000))
        self.label.setText(m)

    def done(self):
        self.hide()


def open_path(p: str | Path, select: bool = False):
    p = Path(p)
    if sys.platform == "win32":
        if select and p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p if p.is_dir() else p.parent))  # type: ignore[attr-defined]


def label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, icon_name: str | None = None, obj: str = "", tip: str = "", color: str | None = None):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if icon_name:
        b.setIcon(T.icon(icon_name, color or ("#0B0D12" if obj in ("primary", "round") else T.TEXT), 18))
        b.setIconSize(QSize(18, 18))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def card(obj: str = "card", margins=(18, 16, 18, 16), spacing=10) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(obj)
    v = QVBoxLayout(f)
    v.setContentsMargins(*margins)
    v.setSpacing(spacing)
    return f, v


def sep() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    return f


def error_box(parent, msg: str, title: str = "ReadRush"):
    first, _, details = msg.partition("\n\n")
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(first[:700])
    if details:
        box.setDetailedText(details)
    box.exec()


class Page(QScrollArea):
    """Scrollable page with a centered, max-width column."""

    def __init__(self, title: str, subtitle: str = "", max_width: int = 1040):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(36, 30, 36, 30)
        col = QWidget()
        col.setMaximumWidth(max_width)
        self.body = QVBoxLayout(col)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(16)
        outer.addStretch(1)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        self.setWidget(inner)
        if title:
            head = QVBoxLayout()
            head.setSpacing(4)
            head.addWidget(label(title, "h1"))
            if subtitle:
                head.addWidget(label(subtitle, "muted", True))
            self.body.addLayout(head)

    def finish(self):
        self.body.addStretch(1)


class Segmented(QFrame):
    """Pill-style single choice control."""
    changed = Signal(str)

    def __init__(self, options: list[str], value: str | None = None, tips: dict | None = None):
        super().__init__()
        self.setObjectName("segbar")
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for o in options:
            b = QPushButton(o)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if tips and o in tips:
                b.setToolTip(tips[o])
            self.group.addButton(b)
            self.buttons[o] = b
            h.addWidget(b)
            b.clicked.connect(lambda _=False, o=o: self.changed.emit(o))
        self.setValue(value if value in self.buttons else options[0])
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return next(iter(self.buttons))

    def setValue(self, v: str):
        if v in self.buttons:
            self.buttons[v].setChecked(True)


class DropZone(QFrame):
    """Big friendly drop area for files/folders, with a browse button."""
    dropped = Signal(list)

    def __init__(self, title: str, hint: str, icon_name: str = "upload", folders: bool = True,
                 filter_: str = AUDIO_FILTER, height: int = 170):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(height)
        self.filter_, self.folders = filter_, folders
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(T.pixmap(icon_name, T.ACCENT, 34))
        ic.setAlignment(Qt.AlignCenter)
        t = label(title, "h2")
        t.setAlignment(Qt.AlignCenter)
        s = label(hint, "muted")
        s.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        b1 = button("Choose files", "plus")
        b1.clicked.connect(self._browse_files)
        row.addWidget(b1)
        if folders:
            b2 = button("Choose folder", "folder")
            b2.clicked.connect(self._browse_folder)
            row.addWidget(b2)
        for w in (ic, t, s):
            v.addWidget(w)
        v.addLayout(row)

    def _browse_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", self.filter_)
        if fs:
            self.dropped.emit(fs)

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder (sub-folders included)")
        if d:
            self.dropped.emit([d])

    def _hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, _e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()])


class IconBadge(QLabel):
    def __init__(self, icon_name: str, color: str, size: int = 40):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        c = QColor(color)
        self.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},38); border-radius: {size // 3}px;")
        self.setPixmap(T.pixmap(icon_name, color, int(size * 0.5)))


class Toast(QFrame):
    """Small auto-hiding notification in the bottom-right corner."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 16, 10)
        self.ic = QLabel()
        self.text = label("")
        self.text.setStyleSheet("font-weight: 600;")
        h.addWidget(self.ic)
        h.addWidget(self.text)
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade)
        self.hide()

    def show_message(self, text: str, kind: str = "ok"):
        color = {"ok": T.SUCCESS, "info": T.ACCENT2, "err": T.DANGER}.get(kind, T.ACCENT)
        self.ic.setPixmap(T.pixmap({"ok": "check", "err": "x"}.get(kind, "spark"), color, 18))
        self.text.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 70)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setDuration(180)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(3800)

    def _fade(self):
        self.anim.stop()
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self._hide_once)
        self.anim.start()

    def _hide_once(self):
        try:
            self.anim.finished.disconnect(self._hide_once)
        except Exception:
            pass
        if self.eff.opacity() < 0.05:
            self.hide()


class Waveform(QWidget):
    """Waveform with playhead; click to seek."""
    seek = Signal(float)

    def __init__(self, color: str):
        super().__init__()
        self.color = QColor(color)
        self.peaks = np.zeros(1)
        self.playhead = 0.0
        self.dim = False
        self.setMinimumHeight(46)
        self.setCursor(Qt.PointingHandCursor)

    def set_audio(self, audio: np.ndarray, bins: int = 700):
        mono = np.abs(audio).max(axis=0) if audio.ndim > 1 else np.abs(audio)
        n = len(mono) // bins
        self.peaks = mono[: n * bins].reshape(bins, n).max(axis=1) if n >= 1 else (mono if mono.size else np.zeros(1))
        m = float(self.peaks.max()) if self.peaks.size else 0.0
        self.peaks = self.peaks / m if m > 0 else self.peaks
        self.update()

    def mousePressEvent(self, ev):
        if self.width() > 0:
            self.seek.emit(max(0.0, min(1.0, ev.position().x() / self.width())))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        col = QColor(self.color)
        col.setAlpha(55 if self.dim else 255)
        played = QColor(col)
        played.setAlpha(110 if self.dim else 140)
        n = max(1, len(self.peaks))
        bw = w / n
        mid = h / 2
        path_a, path_b = QPainterPath(), QPainterPath()
        xh = self.playhead * w
        for i, v in enumerate(self.peaks):
            hh = max(1.0, float(v) * (h / 2 - 2))
            x = i * bw
            (path_b if x < xh else path_a).addRoundedRect(QRectF(x, mid - hh, max(1.0, bw * 0.7), 2 * hh), 1, 1)
        p.fillPath(path_a, col)
        p.fillPath(path_b, played)
        p.setPen(QColor("#FFFFFF"))
        p.drawLine(int(xh), 2, int(xh), h - 2)
        p.end()
