"""Reusable PDFRush widgets."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QSize, Qt, QThread, QTimer, Signal,
                            Slot)
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QLayout, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme as T

PDF_FILTER = "PDF files (*.pdf);;All files (*)"


def ext_filter(exts: list[str], label_: str = "Supported files") -> str:
    return f"{label_} (" + " ".join("*" + e for e in exts) + ");;All files (*)"


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
            from ..core.util import PDFIUM_LOCK
            kw = dict(self.kwargs)
            if self.wp:
                kw["progress"] = lambda f, m: self.progress.emit(float(f), str(m))
            with PDFIUM_LOCK:
                res = self.fn(*self.args, **kw)
            self.done.emit(res)
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


def error_box(parent, msg: str, title: str = "PDFRush"):
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
                 filter_: str = PDF_FILTER, height: int = 170):
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


# ===================================================================== PDFRush additions
def collect_files(items: list[str], exts: list[str]) -> list[Path]:
    """Expand dropped files/folders into supported files (folders are searched recursively)."""
    out: list[Path] = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in exts)
        elif p.is_file() and (not exts or p.suffix.lower() in exts):
            out.append(p)
    return out


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def pil_to_pixmap(img) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def file_thumb(path: Path, size: int = 120, page: int = 0):
    """Small preview pixmap for a PDF page or an image (None if it can't be rendered)."""
    from ..core.util import PDFIUM_LOCK
    try:
        if path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium
            if not PDFIUM_LOCK.acquire(timeout=0.05):
                return None
            try:
                doc = pdfium.PdfDocument(str(path))
                pg = doc[page]
                w, h = pg.get_size()
                img = pg.render(scale=size / max(w, h) * 1.5).to_pil()
                pg.close()
                doc.close()
            finally:
                PDFIUM_LOCK.release()
        else:
            from PIL import Image
            img = Image.open(path)
            img.thumbnail((size * 2, size * 2))
        img.thumbnail((size * 2, size * 2))
        pm = pil_to_pixmap(img)
        pm.setDevicePixelRatio(2)
        return pm
    except Exception:
        return None


class FlowLayout(QLayout):
    """Wrapping layout for tool tiles (Qt's classic flow layout example)."""

    def __init__(self, parent=None, spacing: int = 14):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class ParamForm(QWidget):
    """Builds input controls from a tool's Param list; handles show_if visibility."""
    changed = Signal()

    def __init__(self, params, values: dict | None = None):
        from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit,
                                       QPlainTextEdit, QSpinBox)
        super().__init__()
        self.params = params
        self.widgets: dict = {}
        self.rows: dict = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        values = values or {}
        for p in params:
            if p.key.startswith("_"):
                continue
            v = values.get(p.key, p.default)
            if p.kind == "choice":
                w = QComboBox()
                w.addItems([str(o) for o in p.options])
                if str(v) in [str(o) for o in p.options]:
                    w.setCurrentText(str(v))
                w.currentTextChanged.connect(self._on_change)
            elif p.kind == "bool":
                w = QCheckBox(p.label)
                w.setChecked(bool(v))
                w.toggled.connect(self._on_change)
            elif p.kind == "int":
                w = QSpinBox()
                w.setRange(int(p.minimum), int(p.maximum))
                w.setValue(int(v or 0))
                w.valueChanged.connect(self._on_change)
            elif p.kind == "float":
                w = QDoubleSpinBox()
                w.setRange(float(p.minimum), float(p.maximum))
                w.setDecimals(1)
                w.setValue(float(v or 0))
                w.valueChanged.connect(self._on_change)
            elif p.kind == "multiline":
                w = QPlainTextEdit(str(v or ""))
                w.setFixedHeight(90)
                w.setStyleSheet("font-size: 13px; padding: 8px;")
                w.textChanged.connect(self._on_change)
            elif p.kind == "color":
                w = QPushButton(str(v or "#000000"))
                w.setProperty("color", str(v or "#000000"))

                def pick(_=False, w=w):
                    from PySide6.QtGui import QColor as _QC
                    c = QColorDialog.getColor(_QC(w.property("color")), self, "Choose a colour")
                    if c.isValid():
                        self._set_color(w, c.name())
                        self._on_change()
                w.clicked.connect(pick)
                self._set_color(w, str(v or "#000000"))
            elif p.kind == "file":
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(0, 0, 0, 0)
                ed = QLineEdit(str(v or ""))
                ed.setPlaceholderText("Choose a file…")
                bt = button("Browse", "folder")

                def browse(_=False, ed=ed):
                    f, _x = QFileDialog.getOpenFileName(self, "Choose a file", "",
                                                        "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
                    if f:
                        ed.setText(f)
                bt.clicked.connect(browse)
                ed.textChanged.connect(self._on_change)
                hl.addWidget(ed, 1)
                hl.addWidget(bt)
                w.edit = ed
            else:   # text | password | pages
                w = QLineEdit(str(v if v is not None else ""))
                if p.kind == "password":
                    w.setEchoMode(QLineEdit.Password)
                if p.kind == "pages":
                    w.setPlaceholderText("all   (e.g. 1-3, 5, 8-)")
                w.textChanged.connect(self._on_change)
            if p.hint:
                w.setToolTip(p.hint)
            self.widgets[p.key] = w
            if p.kind == "bool":
                form.addRow("", w)
                lab = None
            else:
                lab = label(p.label, "muted")
                form.addRow(lab, w)
            hint = None
            if p.hint and p.kind not in ("bool",):
                hint = label(p.hint, "faint", True)
                form.addRow("", hint)
            self.rows[p.key] = (lab, w, hint)
        self._apply_visibility()

    @staticmethod
    def _set_color(w, c):
        w.setProperty("color", c)
        w.setText(c.upper())
        w.setStyleSheet(f"QPushButton {{ border-left: 18px solid {c}; text-align: left; }}")

    def _on_change(self, *_):
        self._apply_visibility()
        self.changed.emit()

    def _apply_visibility(self):
        vals = self.values()
        for p in self.params:
            if p.key not in self.rows:
                continue
            show = True
            if p.show_if:
                key, want = p.show_if
                want = want if isinstance(want, (tuple, list)) else (want,)
                show = vals.get(key) in want
            for w in self.rows[p.key]:
                if w is not None:
                    w.setVisible(show)

    def values(self) -> dict:
        from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QSpinBox
        out = {}
        for p in self.params:
            w = self.widgets.get(p.key)
            if w is None:
                continue
            if isinstance(w, QComboBox):
                out[p.key] = w.currentText()
            elif isinstance(w, QCheckBox):
                out[p.key] = w.isChecked()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                out[p.key] = w.value()
            elif isinstance(w, QPlainTextEdit):
                out[p.key] = w.toPlainText()
            elif isinstance(w, QLineEdit):
                out[p.key] = w.text()
            elif isinstance(w, QPushButton):
                out[p.key] = w.property("color")
            elif hasattr(w, "edit"):
                out[p.key] = w.edit.text()
        return out
