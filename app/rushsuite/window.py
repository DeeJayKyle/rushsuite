"""RushSuite shell: one window that hosts PDFRush (every PDF tool) and ReadRush (read & listen, voice typing,
AI, podcasts, meetings). A slim rail on the left switches between them; they share the AI brain."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import APP_NAME, __version__

RAIL_STYLE = """
QWidget#rail { background: #08090D; border-right: 1px solid #262C3D; }
QPushButton#railbtn { background: transparent; border: none; border-radius: 14px; padding: 8px 0 6px 0;
                      color: #8C93A9; font-size: 11px; font-weight: 700; }
QPushButton#railbtn:hover { background: #151924; color: #ECEEF5; }
QPushButton#railbtn:checked { background: #1F2432; color: #ECEEF5; }
QLabel#railver { color: #5D6479; font-size: 10px; }
"""


def _no_title_bar(_w):      # embedded windows must not become native top-level frames
    return None


def build_windows(files: list[str]):
    """Create both apps as embeddable widgets (imports are deferred so the splash shows quickly)."""
    import pdfrush
    from pdfrush.ui import theme as PT
    from readrush.ui import theme as RT
    pdfrush.SUITE = True
    _share_ai()
    if not hasattr(RT, "_orig_dark_title_bar"):
        RT._orig_dark_title_bar = RT.dark_title_bar
    PT.dark_title_bar = _no_title_bar
    RT.dark_title_bar = _no_title_bar
    from pdfrush.ui.main_window import MainWindow as PdfMain
    from readrush.ui.main_window import MainWindow as ReadMain

    class EmbeddedRead(ReadMain):
        suite = None

        def showNormal(self):            # ReadRush asks to be shown -> bring its tab forward
            if self.suite is not None:
                self.suite.show_read()

        def _show(self):
            if self.suite is not None:
                self.suite.bring_front("read")

        def raise_(self):
            if self.suite is not None:
                self.suite.bring_front("read")

        def activateWindow(self):
            if self.suite is not None:
                self.suite.activateWindow()

    read = EmbeddedRead()
    pdf = PdfMain()
    return read, pdf, PT.STYLE, RT.STYLE


def _share_ai():
    """PDF tools use ReadRush's AI brain (same keys, same offline model, one local server)."""
    import sys

    import readrush.paths as rpaths
    from readrush.engines import llm as rllm
    sys.modules["pdfrush.core.llm"] = rllm
    import pdfrush.core as pcore
    pcore.llm = rllm
    from pdfrush.core import ai as pai
    pai.llm = rllm
    pai.paths = rpaths


class SuiteWindow(QMainWindow):
    def __init__(self, files: list[str] | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        from readrush import paths as rpaths
        icon = rpaths.ASSETS_DIR / "icon.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.read, self.pdf, pdf_style, read_style = build_windows(files or [])
        QApplication.instance().setStyleSheet(read_style + RAIL_STYLE)
        self.pdf.setStyleSheet(pdf_style)
        for w in (self.read, self.pdf):
            w.setWindowFlags(Qt.Widget)
        self.read.suite = self
        self.pdf.suite = self

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(78)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(8, 14, 8, 12)
        rv.setSpacing(8)
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(QIcon(str(icon)).pixmap(40, 40) if icon.exists() else self.windowIcon().pixmap(40, 40))
        rv.addWidget(logo)
        rv.addSpacing(10)
        from pdfrush.ui import theme as PT
        from readrush.ui import theme as RT
        self.group = QButtonGroup(self)
        self.rail_buttons = {}
        for key, text, ic in (("pdf", "PDF", PT.icon("pdf", PT.ACCENT, 28)), ("read", "Read &\nListen", RT.icon("volume", RT.ACCENT, 28))):
            b = QPushButton(text)
            b.setObjectName("railbtn")
            b.setIcon(ic)
            b.setIconSize(QSize(28, 28))
            b.setCheckable(True)
            b.setFixedSize(62, 70)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.bring_front(k))
            self.group.addButton(b)
            self.rail_buttons[key] = b
            rv.addWidget(b, 0, Qt.AlignHCenter)
        rv.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("railver")
        ver.setAlignment(Qt.AlignCenter)
        rv.addWidget(ver)
        h.addWidget(rail)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.pdf)
        self.stack.addWidget(self.read)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        try:                                              # tray belongs to ReadRush (hotkeys keep working)
            self.read.tray.setToolTip(APP_NAME)
            acts = self.read._tray_menu.actions()
            if acts:
                acts[0].setText(f"Open {APP_NAME}")
        except Exception:
            pass
        self.bring_front("pdf")
        if files:
            fs = [Path(f) for f in files if Path(f).exists()]
            if fs:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(500, lambda: self.pdf.pick_tool_for(fs))

    # ------------------------------------------------------------------ switching
    def bring_front(self, key: str):
        w = self.pdf if key == "pdf" else self.read
        self.stack.setCurrentWidget(w)
        self.rail_buttons[key].setChecked(True)
        self.setWindowTitle(f"{APP_NAME} - {'PDF tools' if key == 'pdf' else 'Read & Listen'}")
        if self.isMinimized() or not self.isVisible():
            QMainWindow.showNormal(self)
        QMainWindow.raise_(self)

    def show_read(self, page: str | None = None):
        self.bring_front("read")
        if page:
            self.read.go(page)

    def listen(self, files):
        """Open documents in Read & Listen and start reading."""
        self.bring_front("read")
        self.read.pages["library"].import_paths([str(f) for f in files], autoplay=True)

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, e):
        super().showEvent(e)
        from readrush.ui import theme as RT
        orig = getattr(RT, "_orig_dark_title_bar", None)
        if orig:
            orig(self)

    def closeEvent(self, e):
        r = self.read
        if not r._quitting and r.tray.isVisible():
            e.ignore()
            self.hide()
            from readrush import paths as rpaths
            if not rpaths.settings.get("_suite_tray_hint"):
                r.tray.showMessage(f"{APP_NAME} is still running",
                                   "Voice typing and read-aloud hotkeys keep working. Right-click the tray icon to quit.")
                rpaths.settings["_suite_tray_hint"] = True
                rpaths.settings.save()
            return
        r.quit_app()
