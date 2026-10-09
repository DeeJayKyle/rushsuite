"""Home, Library, Scan & Listen, Ask AI."""
from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QTextBrowser, QVBoxLayout)

from .. import paths
from ..engines import ai, docs, library, ocr
from . import theme as T
from .widgets import Busy, DropZone, IconBadge, Page, Segmented, button, card, error_box, label, run_bg


# ===================================================================== HOME
class Tile(QFrame):
    clicked = Signal()

    def __init__(self, icon_name, color, title, text):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(138)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.addWidget(IconBadge(icon_name, color, 42))
        v.addStretch(1)
        v.addWidget(label(title, "h2"))
        v.addWidget(label(text, "muted", True))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class HomePage(Page):
    def __init__(self, win):
        h = time.localtime().tm_hour
        greet = "Good morning" if h < 12 else ("Good afternoon" if h < 17 else "Good evening")
        super().__init__(f"{greet} 👋", "Listen to anything, write with your voice and get answers, offline.")
        self.win = win
        # quick listen box
        c, v = card()
        row = QHBoxLayout()
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("Paste text or a web link, then press Listen…")
        self.quick.returnPressed.connect(self._quick)
        go = button("Listen", "play", "primary")
        go.clicked.connect(self._quick)
        row.addWidget(self.quick, 1)
        row.addWidget(go)
        v.addLayout(row)
        self.body.addWidget(c)

        grid = QGridLayout()
        grid.setSpacing(14)
        tiles = [("book", T.ACCENT, "Listen", "PDFs, books, docs, web pages", "library"),
                 ("scan", "#FFC857", "Scan & listen", "Photos, scans, screenshots", "scan"),
                 ("keyboard", "#3DDC97", "Voice typing", "Dictate into any app", "typing"),
                 ("chat", "#36D6E7", "Ask AI", "Answers from your documents", "ask"),
                 ("podcast", "#FF6FA3", "AI podcast", "Turn anything into a show", "podcasts"),
                 ("meeting", "#FF8A4C", "Meeting notes", "Record, transcribe, summarize", "meetings")]
        for i, (ic, col, t, d, key) in enumerate(tiles):
            tile = Tile(ic, col, t, d)
            tile.clicked.connect(lambda k=key: win.go(k))
            grid.addWidget(tile, i // 3, i % 3)
        self.body.addLayout(grid)
        self.body.addWidget(label("Continue listening", "h2"))
        self.recent = QVBoxLayout()
        self.recent.setSpacing(8)
        self.body.addLayout(self.recent)
        hk = paths.settings
        self.tip = label(f"Tip: press {pretty_hotkey(hk.get('dictation_hotkey'))} anywhere to dictate, and "
                         f"{pretty_hotkey(hk.get('read_hotkey'))} to hear selected text.", "faint", True)
        self.body.addWidget(self.tip)
        self.finish()
        self.refresh()

    def refresh(self):
        while self.recent.count():
            w = self.recent.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = [i for i in library.all_items({"doc", "web", "scan", "text", "note"})][:4]
        if not items:
            self.recent.addWidget(label("Nothing yet: import a document to start.", "faint"))
        for it in items:
            self.recent.addWidget(ItemRow(it, self.win))

    def _quick(self):
        t = self.quick.text().strip()
        if not t:
            t = QApplication.clipboard().text().strip()
        if not t:
            return
        self.quick.clear()
        self.win.pages["library"].add_text_or_link(t, autoplay=True)


def pretty_hotkey(h: str | None) -> str:
    return (h or "").replace("<", "").replace(">", "").replace("+", " + ").title()


class ItemRow(QFrame):
    def __init__(self, it: library.Item, win):
        super().__init__()
        self.setObjectName("card2")
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.addWidget(IconBadge(T.KIND_ICONS.get(it.kind, "book"), T.KIND_COLORS.get(it.kind, T.ACCENT), 36))
        v = QVBoxLayout()
        v.setSpacing(2)
        t = label(it.title)
        t.setStyleSheet("font-weight: 600;")
        n = max(1, len(re.split(r"(?<=[.!?])\s+", it.text)))
        pct = min(100, int(100 * it.progress / n))
        v.addWidget(t)
        v.addWidget(label(f"{library.KINDS.get(it.kind, '')} · {it.words:,} words · {pct}% listened", "faint"))
        h.addLayout(v, 1)
        b = button("", "play", "ghost", "Listen")
        b.clicked.connect(lambda: win.open_item(it, True))
        h.addWidget(b)
        self.it, self.win = it, win

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.open_item(self.it, False)


# ===================================================================== LIBRARY
FILTERS = {"All": None, "Documents": {"doc", "text"}, "Web": {"web"}, "Scans": {"scan"}, "Notes": {"note"},
           "Meetings": {"meeting"}, "Podcasts": {"podcast"}}


class LibraryPage(Page):
    def __init__(self, win):
        super().__init__("Library", "Everything you can listen to. Drop files, paste text, or add a web link.")
        self.win = win
        self.drop = DropZone("Drop documents here", "PDF · EPUB · Word · Excel · TXT · HTML · images (scanned with OCR)",
                             "book", folders=True, filter_=docs.FILE_FILTER, height=150)
        self.drop.dropped.connect(self.import_paths)
        self.body.addWidget(self.drop)
        row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://… web article link")
        self.link.returnPressed.connect(self._add_link)
        bl = button("Add link", "link")
        bl.clicked.connect(self._add_link)
        bp = button("Paste text", "clipboard")
        bp.clicked.connect(self._paste)
        row.addWidget(self.link, 1)
        row.addWidget(bl)
        row.addWidget(bp)
        self.body.addLayout(row)
        self.busy = Busy()
        self.body.addWidget(self.busy)
        frow = QHBoxLayout()
        self.filter = Segmented(list(FILTERS))
        self.filter.changed.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self.refresh)
        frow.addWidget(self.filter)
        frow.addWidget(self.search, 1)
        self.body.addLayout(frow)
        self.list = QListWidget()
        self.list.setMinimumHeight(360)
        self.list.itemDoubleClicked.connect(lambda it: win.open_item(it.data(Qt.UserRole), True))
        self.body.addWidget(self.list)
        act = QHBoxLayout()
        for text, ic, fn in (("Listen", "play", lambda: self._sel(lambda i: win.open_item(i, True))),
                             ("Open", "book", lambda: self._sel(lambda i: win.open_item(i, False))),
                             ("Rename", "text", lambda: self._sel(self._rename)),
                             ("Delete", "trash", lambda: self._sel(self._delete))):
            b = button(text, ic, "primary" if text == "Listen" else "")
            b.clicked.connect(fn)
            act.addWidget(b)
        act.addStretch(1)
        self.body.addLayout(act)
        self.finish()
        self.refresh()

    def refresh(self, *_):
        self.list.clear()
        for it in library.all_items(FILTERS[self.filter.value()], self.search.text()):
            li = QListWidgetItem(T.icon(T.KIND_ICONS.get(it.kind, "book"), T.KIND_COLORS.get(it.kind, T.ACCENT), 22),
                                 f"{it.title}\n{library.KINDS.get(it.kind, '')} · {it.words:,} words · "
                                 f"~{max(1, round(it.minutes))} min · {time.strftime('%d %b %Y', time.localtime(it.updated))}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)

    def _sel(self, fn):
        it = self.list.currentItem()
        if it:
            fn(it.data(Qt.UserRole))

    def _rename(self, item):
        name, ok = QInputDialog.getText(self, "Rename", "Title:", text=item.title)
        if ok and name.strip():
            item.title = name.strip()
            library.save(item)
            self.win.library_changed()

    def _delete(self, item):
        if QMessageBox.question(self, "Delete", f"Delete '{item.title}'?") == QMessageBox.Yes:
            library.delete(item)
            self.win.library_changed()

    # ---------------- importing
    def import_paths(self, items: list[str], autoplay: bool = False):
        files = []
        for p in map(Path, items):
            if p.is_dir():
                files += sorted(f for f in p.rglob("*") if f.suffix.lower() in docs.DOC_EXT | docs.IMG_EXT)
            else:
                files.append(p)
        if not files:
            return
        self.busy.start("Importing…")

        def job(progress):
            out = []
            for i, f in enumerate(files):
                imp = docs.from_file(str(f), lambda fr, m, i=i: progress((i + fr) / len(files), m))
                out.append(library.add_imported(imp))
            return out

        def done(items):
            self.busy.done()
            self.win.library_changed()
            self.win.toast(f"Added {len(items)} item{'s' if len(items) != 1 else ''}", "ok")
            if len(items) == 1:
                self.win.open_item(items[0], autoplay)

        def fail(msg):
            self.busy.done()
            error_box(self, msg)
        run_bg(self, job, on_done=done, on_fail=fail, on_progress=self.busy.update_)

    def add_text_or_link(self, t: str, autoplay: bool = False):
        if re.match(r"^(https?://|www\.)\S+$", t.strip()):
            self._fetch(t.strip(), autoplay)
        else:
            it = library.add_imported(docs.from_text(t))
            self.win.library_changed()
            self.win.open_item(it, autoplay)

    def _add_link(self):
        u = self.link.text().strip()
        if u:
            self.link.clear()
            self._fetch(u, False)

    def _fetch(self, url, autoplay):
        self.busy.start("Fetching page…")

        def done(it):
            self.busy.done()
            self.win.library_changed()
            self.win.open_item(it, autoplay)

        def fail(msg):
            self.busy.done()
            error_box(self, f"Couldn't load that page.\n\n{msg}")
        run_bg(self, lambda progress: library.add_imported(docs.from_url(url, progress)),
               on_done=done, on_fail=fail, on_progress=self.busy.update_)

    def _paste(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Paste text")
        dlg.resize(640, 460)
        v = QVBoxLayout(dlg)
        title = QLineEdit()
        title.setPlaceholderText("Title (optional)")
        box = QPlainTextEdit()
        box.setPlainText(QApplication.clipboard().text())
        ok = button("Add & listen", "play", "primary")
        ok.clicked.connect(dlg.accept)
        v.addWidget(title)
        v.addWidget(box, 1)
        v.addWidget(ok)
        if dlg.exec() == QDialog.Accepted and box.toPlainText().strip():
            it = library.add_imported(docs.from_text(box.toPlainText(), title.text().strip()))
            self.win.library_changed()
            self.win.open_item(it, True)


# ===================================================================== SCAN
class CameraDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Snap a page")
        self.resize(760, 600)
        v = QVBoxLayout(self)
        self.view = QLabel("Starting camera…")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(640, 480)
        v.addWidget(self.view, 1)
        b = button("Capture", "camera", "primary")
        b.clicked.connect(self._capture)
        v.addWidget(b)
        self.frame = None
        self.image = None
        try:
            import cv2
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        except Exception as e:  # noqa: BLE001
            self.cap = None
            self.view.setText(f"No camera available: {e}")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._grab)
        self.timer.start(40)

    def _grab(self):
        if not self.cap:
            return
        ok, frame = self.cap.read()
        if not ok:
            return
        self.frame = frame
        rgb = frame[:, :, ::-1].copy()
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        self.view.setPixmap(QPixmap.fromImage(img).scaled(self.view.size(), Qt.KeepAspectRatio,
                                                          Qt.SmoothTransformation))

    def _capture(self):
        if self.frame is not None:
            from PIL import Image
            self.image = Image.fromarray(self.frame[:, :, ::-1].copy())
            self.accept()

    def done(self, r):
        self.timer.stop()
        if self.cap:
            self.cap.release()
        super().done(r)


class ScanPage(Page):
    def __init__(self, win):
        super().__init__("Scan & listen", "Snap a page, drop photos or screenshots: the text is recognised offline "
                                          "and read aloud.")
        self.win = win
        self.images: list = []
        self.drop = DropZone("Drop photos or screenshots", "JPG · PNG · TIFF · multiple pages in order", "scan",
                             folders=False, filter_="Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)", height=140)
        self.drop.dropped.connect(lambda fs: self.add_images(fs))
        self.body.addWidget(self.drop)
        row = QHBoxLayout()
        cam = button("Use camera", "camera")
        cam.clicked.connect(self._camera)
        clip = button("Paste screenshot", "clipboard")
        clip.clicked.connect(self._clipboard)
        clr = button("Start over", "trash", "ghost")
        clr.clicked.connect(self._clear)
        row.addWidget(cam)
        row.addWidget(clip)
        row.addStretch(1)
        row.addWidget(clr)
        self.body.addLayout(row)
        self.thumbs = QHBoxLayout()
        self.thumbs.setAlignment(Qt.AlignLeft)
        self.body.addLayout(self.thumbs)
        self.busy = Busy()
        self.body.addWidget(self.busy)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Recognised text appears here, and you can fix anything before listening.")
        self.text.setMinimumHeight(260)
        self.body.addWidget(self.text)
        act = QHBoxLayout()
        lb = button("Listen", "play", "primary")
        lb.clicked.connect(lambda: self._save(True))
        sb = button("Save to library", "book")
        sb.clicked.connect(lambda: self._save(False))
        act.addWidget(lb)
        act.addWidget(sb)
        act.addStretch(1)
        self.body.addLayout(act)
        if not ocr.available():
            self.body.addWidget(label("The OCR engine isn't installed. Run build.bat again.", "faint"))
        self.finish()

    def add_images(self, items):
        from PIL import Image
        imgs = []
        for x in items:
            try:
                imgs.append(x if not isinstance(x, str) else Image.open(x).copy())
            except Exception as e:  # noqa: BLE001
                self.win.toast(f"Can't open {Path(str(x)).name}: {e}", "err")
        if not imgs:
            return
        for im in imgs:
            th = im.copy()
            th.thumbnail((110, 140))
            lab = QLabel()
            data = th.convert("RGB").tobytes()
            qi = QImage(data, th.width, th.height, 3 * th.width, QImage.Format_RGB888).copy()
            lab.setPixmap(QPixmap.fromImage(qi))
            lab.setStyleSheet(f"border: 1px solid {T.BORDER}; border-radius: 6px;")
            self.thumbs.addWidget(lab)
        self.images += imgs
        self.busy.start("Recognising text…")

        def job(progress):
            out = []
            for i, im in enumerate(imgs):
                progress(i / len(imgs), f"Scanning page {i + 1}/{len(imgs)}")
                out.append(ocr.image_to_text(im))
            return "\n\n".join(out)

        def done(text):
            self.busy.done()
            cur = self.text.toPlainText().strip()
            self.text.setPlainText((cur + "\n\n" + text).strip() if cur else text)
            if not text.strip():
                self.win.toast("No text found in that image", "err")

        def fail(msg):
            self.busy.done()
            error_box(self, msg)
        run_bg(self, job, on_done=done, on_fail=fail, on_progress=self.busy.update_)

    def _camera(self):
        dlg = CameraDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.image is not None:
            self.add_images([dlg.image])

    def _clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.win.toast("No image on the clipboard (Win + Shift + S takes a screenshot)", "info")
            return
        from PIL import Image
        img = img.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        buf = bytes(img.constBits())[: img.bytesPerLine() * h]
        pil = Image.frombuffer("RGB", (w, h), buf, "raw", "RGB", img.bytesPerLine(), 1).copy()
        self.add_images([pil])

    def _clear(self):
        self.images = []
        self.text.clear()
        while self.thumbs.count():
            w = self.thumbs.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _save(self, play: bool):
        t = self.text.toPlainText().strip()
        if not t:
            return
        imp = docs.from_text(t)
        imp.kind = "scan"
        it = library.add_imported(imp)
        self.win.library_changed()
        self.win.open_item(it, play)


# ===================================================================== ASK AI
class AskPage(Page):
    def __init__(self, win):
        super().__init__("Ask AI", "Ask questions across your documents, notes and meetings, by typing or by voice.")
        self.win = win
        self.history: list[dict] = []
        top = QHBoxLayout()
        top.addWidget(label("Search in", "muted"))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(320)
        top.addWidget(self.scope)
        top.addStretch(1)
        self.brain = label("", "pill")
        top.addWidget(self.brain)
        clear = button("New chat", "plus", "ghost")
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        self.body.addLayout(top)
        self.chat = QTextBrowser()
        self.chat.setMinimumHeight(420)
        self.chat.setStyleSheet("QTextBrowser { font-size: 14px; padding: 14px; }")
        self.body.addWidget(self.chat)
        self.busy = Busy()
        self.body.addWidget(self.busy)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("e.g. What are the side effects mentioned? Summarise chapter 2…")
        self.q.returnPressed.connect(self.ask)
        self.mic = button("", "mic", tip="Ask by voice")
        self.mic.setCheckable(True)
        self.mic.toggled.connect(self._voice)
        send = button("Ask", "send", "primary")
        send.clicked.connect(lambda: self.ask())
        row.addWidget(self.q, 1)
        row.addWidget(self.mic)
        row.addWidget(send)
        self.body.addLayout(row)
        self.speak = QCheckBox("Read answers aloud (hands-free)")
        self.body.addWidget(self.speak)
        self.finish()
        self.refresh()

    def refresh(self):
        from ..engines import llm
        self.brain.setText(llm.describe())
        cur = self.scope.currentData()
        self.scope.clear()
        self.scope.addItem("All my documents, notes & meetings", "*")
        for it in library.all_items():
            self.scope.addItem(f"{library.KINDS.get(it.kind, '')}: {it.title[:60]}", it.id)
        i = self.scope.findData(cur)
        self.scope.setCurrentIndex(max(0, i))

    def _clear(self):
        self.history = []
        self.chat.clear()

    def _sources(self):
        sid = self.scope.currentData()
        items = library.all_items() if sid == "*" else [library.load(sid)]
        out = []
        for it in items:
            if not it:
                continue
            text = it.text
            if it.kind == "meeting" and it.extra.get("notes"):
                text = it.extra["notes"] + "\n\n" + text
            out.append((it.title, text))
        return out

    def ask(self, question: str | None = None):
        import html
        q = (question or self.q.text()).strip()
        if not q:
            return
        self.q.clear()
        self.chat.append(f"<p><b style='color:{T.ACCENT}'>You</b><br>{html.escape(q)}</p>")
        self.busy.start("Thinking…")
        hist = list(self.history)

        def done(ans):
            self.busy.done()
            self.history += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
            self.chat.append(f"<p><b style='color:{T.ACCENT2}'>ReadRush</b><br>"
                             f"{html.escape(ans).replace(chr(10), '<br>')}</p>")
            if self.speak.isChecked():
                self.win.mini_read("Answer", ans)

        def fail(msg):
            self.busy.done()
            error_box(self, msg, "Ask AI")
        run_bg(self, ai.ask, q, self._sources(), hist, on_done=done, on_fail=fail)

    def _voice(self, on):
        from ..engines import stt, voice_input
        if on:
            self._rec = voice_input.MicRecorder()
            try:
                self._rec.start()
                self.mic.setIcon(T.icon("stop", T.DANGER, 18))
                self.busy.start("Listening… click the mic again when you're done")
            except Exception as e:  # noqa: BLE001
                self.mic.setChecked(False)
                error_box(self, f"Microphone error: {e}")
        else:
            self.mic.setIcon(T.icon("mic", T.TEXT, 18))
            audio = self._rec.stop()
            self.busy.start("Transcribing…")

            def done(text):
                self.busy.done()
                if text.strip():
                    self.speak.setChecked(True)
                    self.ask(text)
            run_bg(self, stt.transcribe, audio, on_done=done,
                   on_fail=lambda m: (self.busy.done(), error_box(self, m)))

