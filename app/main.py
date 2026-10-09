"""RushSuite entry point: PDFRush + ReadRush in one window."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfrush import paths as ppaths  # noqa: E402
from readrush import paths as rpaths  # noqa: E402

rpaths.setup_environment()
ppaths.setup_environment()
LOG = rpaths.config_dir().parent / "RushSuite" / "rushsuite.log"
LOG.parent.mkdir(parents=True, exist_ok=True)


def _excepthook(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "RushSuite", f"{value}\n\nDetails were saved to:\n{LOG}")
    except Exception:
        print(text, file=sys.stderr)


def main() -> int:
    if sys.stdout is None or sys.stderr is None:          # pythonw.exe has no console
        f = open(LOG, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    sys.excepthook = _excepthook
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtGui import QFont, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RushSuite.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("RushSuite")
    app.setQuitOnLastWindowClosed(False)          # keeps running in the tray for the hotkeys
    icon = rpaths.ASSETS_DIR / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    splash = None
    sp = rpaths.ASSETS_DIR / "splash.png"
    if sp.exists():
        splash = QSplashScreen(QPixmap(str(sp)))
        splash.show()
        app.processEvents()
    app.setFont(QFont("Segoe UI", 10))
    from rushsuite.window import SuiteWindow
    w = SuiteWindow(sys.argv[1:])
    w.show()
    if splash:
        splash.finish(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
