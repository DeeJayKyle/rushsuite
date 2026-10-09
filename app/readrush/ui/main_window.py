"""ReadRush main window: sidebar, pages, now-playing bar, voice-typing overlay, tray icon,
global hotkey + browser-extension event pump."""
from __future__ import annotations

import queue
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QProgressBar, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__, paths
from ..engines import bridge, library, reader, voice_input
from . import theme as T
from .pages_a import AskPage, HomePage, LibraryPage, ScanPage, pretty_hotkey
from .pages_b import MeetingsPage, NotesPage, PodcastsPage, SettingsPage, TypingPage, VoicesPage
from .reader_page import ReaderPage
from .widgets import Toast, button, error_box, label, run_bg

NAV = [("home", "Home", "home"), ("library", "Library", "library"), ("reader", "Listen", "book"),
       ("scan", "Scan & listen", "scan"), ("typing", "Voice typing", "keyboard"), ("ask", "Ask AI", "chat"),
       ("podcasts", "Podcasts", "podcast"), ("meetings", "Meetings", "meeting"), ("notes", "Notes", "note"),
       ("voices", "Voices", "voice"), ("settings", "Settings", "settings")]


class ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class AudioFilePlayer:
    """Plays finished audio files (podcasts, exports) through the streaming player."""

    def __init__(self):
        self.p = reader.StreamPlayer()
        self.title = ""

    def play_file(self, path: str, title: str = ""):
        from ..engines import audio_io
        a, _ = audio_io.load_audio(path, sr=self.p.sr, mono=True)
        self.p.clear()
        self.p.push(reader.Segment(0, a[0], [], 0))
        self.title = title or Path(path).stem
        self.p.play()

    @property
    def active(self) -> bool:
        return self.p.buffered() > 0

    def toggle(self):
        if self.p.paused:
            self.p.play()
        else:
            self.p.pause()

    def stop(self):
        self.p.pause()
        self.p.clear()


class DictationOverlay(QWidget):
    """Small always-on-top pill that never steals focus from the app you're typing in."""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        f = QFrame(self)
        f.setObjectName("toast")
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 10, 18, 10)
        self.ic = QLabel()
        self.text = label("")
        self.text.setStyleSheet("font-weight: 700; font-size: 14px;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFixedWidth(90)
        h.addWidget(self.ic)
        h.addWidget(self.text)
        h.addWidget(self.bar)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(f)

    def show_state(self, state: str):
        hk = pretty_hotkey(paths.settings.get("dictation_hotkey"))
        if state == "listening":
            self.ic.setPixmap(T.pixmap("mic", T.DANGER, 20))
            self.text.setText(f"Listening…  ({hk} to finish)")
            self.bar.show()
        elif state == "transcribing":
            self.ic.setPixmap(T.pixmap("spark", T.WARN, 20))
            self.text.setText("Writing…")
            self.bar.hide()
        else:
            self.hide()
            return
        self.adjustSize()
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.center().x() - self.width() // 2, scr.bottom() - self.height() - 40)
        self.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ReadRush")
        self.resize(1360, 880)
        self.setMinimumSize(1100, 720)
        self.audio = AudioFilePlayer()
        self.mini = reader.Reader()
        self.mini_title = ""
        self.dictation = voice_input.Dictation()
        self._quitting = False
        self._tasks = 0

        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        outer.addLayout(main, 1)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(226)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 20, 14, 14)
        sv.setSpacing(3)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(T.pixmap("book", T.ACCENT, 24))
        brand.addWidget(logo)
        brand.addWidget(label("ReadRush", "brand"), 1)
        sv.addLayout(brand)
        sv.addSpacing(14)
        self.nav: dict[str, QPushButton] = {}
        grp = QButtonGroup(self)
        for key, text, ic in NAV:
            if key in ("typing", "voices"):
                sv.addSpacing(8)
            b = QPushButton(f"  {text}")
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setIcon(T.icon(ic, T.MUTED, 19))
            b.setIconSize(QSize(19, 19))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            grp.addButton(b)
            sv.addWidget(b)
            self.nav[key] = b
        sv.addStretch(1)
        self.ai_pill = ClickLabel("")
        self.ai_pill.setObjectName("faint")
        self.ai_pill.setWordWrap(True)
        self.ai_pill.setCursor(Qt.PointingHandCursor)
        self.ai_pill.clicked.connect(lambda: self.go("settings"))
        self.hk_pill = label("", "faint")
        self.hk_pill.setWordWrap(True)
        sv.addWidget(self.hk_pill)
        sv.addWidget(self.ai_pill)
        sv.addWidget(label(f"v{__version__}", "faint"))
        main.addWidget(side)

        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        self.pages = {}
        self.pages["reader"] = ReaderPage(self)
        for key, cls in (("home", HomePage), ("library", LibraryPage), ("scan", ScanPage), ("typing", TypingPage),
                         ("ask", AskPage), ("podcasts", PodcastsPage), ("meetings", MeetingsPage),
                         ("notes", NotesPage), ("voices", VoicesPage), ("settings", SettingsPage)):
            self.pages[key] = cls(self)
        for key, _t, _i in NAV:
            self.stack.addWidget(self.pages[key])

        # ---------------- now playing / activity bar
        self.np = QFrame()
        self.np.setObjectName("activity")
        nh = QHBoxLayout(self.np)
        nh.setContentsMargins(18, 8, 18, 8)
        nh.setSpacing(12)
        self.np_btn = QPushButton()
        self.np_btn.setObjectName("round")
        self.np_btn.setFixedSize(38, 38)
        self.np_btn.setStyleSheet("border-radius: 19px; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;")
        self.np_btn.clicked.connect(self._np_toggle)
        self.np_text = label("")
        self.np_text.setStyleSheet("font-weight: 600;")
        self.task_text = label("", "faint")
        self.task_bar = QProgressBar()
        self.task_bar.setRange(0, 1000)
        self.task_bar.setFixedWidth(200)
        self.task_bar.hide()
        op = button("Open", "book", "ghost")
        op.clicked.connect(lambda: self.go("reader"))
        st = button("", "stop", "ghost", "Stop")
        st.clicked.connect(self._np_stop)
        for w in (self.np_btn, self.np_text):
            nh.addWidget(w)
        nh.addStretch(1)
        for w in (self.task_text, self.task_bar, op, st):
            nh.addWidget(w)
        self.np_open = op
        outer.addWidget(self.np)
        self.setCentralWidget(root)
        self.toast_w = Toast(root)
        self.overlay = DictationOverlay()

        # ---------------- services
        self.dictation.start_hotkeys()
        if paths.settings.get("bridge_enabled", True) and not bridge.start():
            pass   # another ReadRush already owns the port
        self._setup_tray()
        self.pump = QTimer(self)
        self.pump.timeout.connect(self._pump)
        self.pump.start(50)
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start(250)
        self.ai_changed()
        self.go("home")

    # ------------------------------------------------------------ navigation
    def go(self, key: str):
        for k, b in self.nav.items():
            ic = next(i for kk, _, i in NAV if kk == k)
            b.setIcon(T.icon(ic, T.TEXT if k == key else T.MUTED, 19))
        self.nav[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        page = self.pages[key]
        if key in ("home", "library", "ask", "podcasts", "meetings", "notes", "voices") and hasattr(page, "refresh"):
            page.refresh()
        if self.isMinimized() or not self.isVisible():
            self.showNormal()

    def toast(self, text: str, kind: str = "ok"):
        self.toast_w.show_message(text, kind)

    def clipboard_set(self, text: str):
        QApplication.clipboard().setText(text)

    def open_item(self, item, autoplay: bool = False):
        self.stop_mini()
        self.audio.stop()
        self.pages["reader"].open_item(item, autoplay)
        self.go("reader")

    def library_changed(self):
        for k in ("home", "library", "ask", "podcasts", "meetings", "notes"):
            p = self.pages[k]
            if hasattr(p, "refresh"):
                p.refresh()

    def voices_changed(self):
        self.pages["reader"].refresh_voices()
        self.pages["voices"].refresh()
        self.pages["podcasts"].refresh()

    def ai_changed(self):
        from ..engines import llm
        d = llm.describe()
        col = T.SUCCESS if "not set" not in d else T.WARN
        self.ai_pill.setText(f"<span style='color:{col}'>●</span> AI: {d}")
        self.ai_pill.setTextFormat(Qt.RichText)
        hk = pretty_hotkey(paths.settings.get("dictation_hotkey"))
        self.hk_pill.setText(f"🎙 {hk}: voice typing")
        self.pages["reader"].panel.refresh_brain()
        self.pages["ask"].refresh()

    # ------------------------------------------------------------ playback helpers
    def mini_read(self, title: str, text: str, voice: str | None = None):
        """Read a short text (answers, summaries, previews) without losing your place in the document."""
        if not text.strip():
            return
        self.pages["reader"].reader.pause()
        self.audio.stop()
        self.mini.voice = voice or self.pages["reader"].reader.voice
        self.mini.speed = self.pages["reader"].reader.speed
        self.mini.load(text)
        self.mini_title = title
        self.mini.play_from(0)

    def stop_mini(self):
        self.mini.stop()

    def run_task(self, title: str, fn, *args, on_done=None):
        self._tasks += 1
        self.task_bar.show()
        self.task_text.setText(title)

        def prog(f, m):
            self.task_bar.setValue(int(f * 1000))
            self.task_text.setText(f"{title}: {m}")

        def fin(res):
            self._tasks -= 1
            if not self._tasks:
                self.task_bar.hide()
                self.task_text.setText("")
            if on_done:
                on_done(res)

        def fail(msg):
            self._tasks -= 1
            if not self._tasks:
                self.task_bar.hide()
                self.task_text.setText("")
            error_box(self, msg)
        run_bg(self, fn, *args, on_done=fin, on_fail=fail, on_progress=prog)

    def _np_toggle(self):
        if self.mini.playing or (self.mini.sentences and self.mini.player.buffered()):
            self.mini.toggle()
        elif self.audio.active:
            self.audio.toggle()
        else:
            self.pages["reader"].toggle()

    def _np_stop(self):
        self.stop_mini()
        self.audio.stop()
        self.pages["reader"].reader.pause()

    def _tick(self):
        r = self.pages["reader"].reader
        if self.mini.finished:
            self.mini.stop()
            self.mini.finished = False
        if self.mini.playing:
            title, playing = f"🔊 {self.mini_title}", True
        elif self.audio.active:
            title, playing = f"🎧 {self.audio.title}", not self.audio.p.paused
        elif r.sentences:
            title, playing = f"📖 {self.pages['reader'].title}  ·  {int(r.progress() * 100)}%", r.playing
        else:
            title, playing = "", False
        self.np_text.setText(title)
        self.np_btn.setIcon(T.icon("pause" if playing else "play", "#0B0D12", 18))
        self.np_btn.setVisible(bool(title))
        self.np_open.setVisible(bool(r.sentences) and self.stack.currentWidget() is not self.pages["reader"])
        self.np.setVisible(bool(title) or self._tasks > 0)
        if self.dictation.recording:
            self.overlay.bar.setValue(int(min(1.0, self.dictation.rec.level * 12) * 100))

    # ------------------------------------------------------------ hotkeys / extension events
    def _pump(self):
        for _ in range(20):
            try:
                ev = voice_input.events.get_nowait()
            except queue.Empty:
                return
            kind = ev[0]
            if kind == "dictation_state":
                self.overlay.show_state(ev[1])
                self.pages["typing"].set_state(ev[1])
            elif kind == "dictation_text":
                text = ev[1]
                if text:
                    self.pages["typing"].add_history(text)
                    try:
                        voice_input.paste_text(text, self.clipboard_set)
                    except Exception as e:  # noqa: BLE001
                        self.clipboard_set(text)
                        self.toast(f"Copied to clipboard (couldn't type it: {e})", "info")
            elif kind == "read_selection":
                self._read_selection()
            elif kind == "bridge_read":
                _, title, text, url = ev
                it = library.save(library.Item("web", title or "Web page", text, url))
                self.library_changed()
                self.open_item(it, True)
                self.raise_()
                self.activateWindow()
            elif kind == "error":
                self.toast(ev[1], "err")

    def _read_selection(self):
        cb = QApplication.clipboard()
        before = cb.text()
        cb.setText("")
        try:
            voice_input.copy_selection()
        except Exception:
            pass

        def go():
            t = cb.text().strip()
            if not t:
                t = before.strip()
                cb.setText(before)
            if t:
                self.mini_read("Selected text", t)
            else:
                self.toast("Select some text first", "info")
        QTimer.singleShot(250, go)

    # ------------------------------------------------------------ tray & lifecycle
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon() if not QApplication.windowIcon().isNull() else T.icon("book"), self)
        self.tray.setToolTip("ReadRush")
        menu = QMenu()
        for text, fn in (("Open ReadRush", self._show), ("Play / pause", self._np_toggle),
                         ("Read selected text", self._read_selection), (None, None), ("Quit", self.quit_app)):
            if text is None:
                menu.addSeparator()
                continue
            a = QAction(text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._tray_menu = menu

    def _show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        T.dark_title_bar(self)

    def closeEvent(self, e):
        if not self._quitting and self.tray.isVisible():
            e.ignore()
            self.hide()
            if not paths.settings.get("_tray_hint"):
                self.tray.showMessage("ReadRush is still running",
                                      "Voice typing and read-aloud hotkeys keep working. Right-click the tray icon to quit.")
                paths.settings["_tray_hint"] = True
                paths.settings.save()
            return
        super().closeEvent(e)

    def quit_app(self):
        self._quitting = True
        try:
            self.pages["reader"]._save_progress()
            self.pages["notes"]._flush()
        except Exception:
            pass
        self.dictation.stop_hotkeys()
        bridge.stop()
        from ..engines import llm
        llm.LOCAL.stop()
        for p in (self.pages["reader"].reader.player, self.mini.player, self.audio.p):
            p.close()
        self.tray.hide()
        QApplication.quit()
        import os
        os._exit(0)

