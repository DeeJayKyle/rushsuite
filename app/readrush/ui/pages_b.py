"""Voice Typing, Podcasts, Meetings, Notes, Voices, Settings."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QProgressBar, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import paths
from ..engines import ai, library, llm, stt, tts, voice_input
from . import theme as T
from .pages_a import pretty_hotkey
from .widgets import Busy, IconBadge, Page, Segmented, button, card, error_box, label, open_path, run_bg


def form(grid: QGridLayout, r: int, name: str, w, hint=None):
    lb = label(name, "muted")
    lb.setFixedWidth(150)
    grid.addWidget(lb, r, 0)
    grid.addWidget(w, r, 1, Qt.AlignLeft)
    if hint is not None:
        grid.addWidget(hint, r, 2, Qt.AlignLeft)


# ===================================================================== VOICE TYPING
class TypingPage(Page):
    def __init__(self, win):
        super().__init__("Voice typing", "Talk instead of type, in any app: email, Word, WhatsApp Web, Google Docs. "
                                         "Fillers like 'um' are removed and punctuation is fixed for you.")
        self.win = win
        c, v = card()
        h = QHBoxLayout()
        self.badge = IconBadge("mic", T.SUCCESS, 54)
        h.addWidget(self.badge)
        tv = QVBoxLayout()
        self.state = label("Ready", "h2")
        self.hint = label("", "muted", True)
        tv.addWidget(self.state)
        tv.addWidget(self.hint)
        h.addLayout(tv, 1)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setFixedWidth(160)
        h.addWidget(self.level)
        v.addLayout(h)
        self.body.addWidget(c)

        c2, v2 = card()
        v2.addWidget(label("Try it here", "h2"))
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText("Click 'Dictate', speak, then click 'Stop'. Your words appear here.")
        self.box.setMinimumHeight(160)
        v2.addWidget(self.box)
        row = QHBoxLayout()
        self.dict_btn = button("Dictate", "mic", "primary")
        self.dict_btn.setCheckable(True)
        self.dict_btn.toggled.connect(self._local_toggle)
        cp = button("Copy", "clipboard")
        cp.clicked.connect(lambda: (win.clipboard_set(self.box.toPlainText()), win.toast("Copied", "ok")))
        pol = button("Polish with AI", "spark")
        pol.clicked.connect(self._polish_box)
        row.addWidget(self.dict_btn)
        row.addWidget(cp)
        row.addWidget(pol)
        row.addStretch(1)
        v2.addLayout(row)
        self.body.addWidget(c2)

        c3, v3 = card()
        v3.addWidget(label("Settings", "h2"))
        g = QGridLayout()
        g.setVerticalSpacing(10)
        self.enabled = QCheckBox("Voice typing hotkey on")
        self.enabled.setChecked(bool(paths.settings.get("dictation_enabled", True)))
        self.hotkey = QLineEdit(paths.settings.get("dictation_hotkey"))
        self.hotkey.setFixedWidth(220)
        self.read_hotkey = QLineEdit(paths.settings.get("read_hotkey"))
        self.read_hotkey.setFixedWidth(220)
        self.polish = QCheckBox("Polish with AI before typing (slower, smarter)")
        self.polish.setChecked(bool(paths.settings.get("dictation_polish")))
        self.lang = QComboBox()
        for name, code in (("Auto-detect", "auto"), ("English", "en"), ("Swahili", "sw"), ("French", "fr"),
                           ("Spanish", "es"), ("Portuguese", "pt"), ("German", "de"), ("Arabic", "ar"),
                           ("Hindi", "hi"), ("Chinese", "zh"), ("Luganda (experimental)", "lg")):
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(paths.settings.get("stt_language", "auto"))))
        self.model = Segmented(list(stt.SIZES), paths.settings.get("stt_model", "small"),
                               {k: v for k, v in stt.SIZES.items()})
        form(g, 0, "Voice typing", self.enabled)
        form(g, 1, "Dictate hotkey", self.hotkey, label("e.g. <ctrl>+<alt>+<space>", "faint"))
        form(g, 2, "Read selection", self.read_hotkey, label("select text anywhere, press to listen", "faint"))
        form(g, 3, "Language", self.lang)
        form(g, 4, "Accuracy", self.model)
        form(g, 5, "", self.polish)
        g.setColumnStretch(2, 1)
        v3.addLayout(g)
        sv = button("Save settings", "check")
        sv.clicked.connect(self._save)
        v3.addWidget(sv, 0, Qt.AlignLeft)
        self.body.addWidget(c3)
        self.body.addWidget(label("Recent dictations", "h2"))
        self.hist = QListWidget()
        self.hist.setMinimumHeight(140)
        self.hist.itemDoubleClicked.connect(lambda it: (win.clipboard_set(it.text()), win.toast("Copied", "ok")))
        self.body.addWidget(self.hist)
        self.finish()
        self._rec = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)
        self.set_state("idle")

    def set_state(self, st: str):
        hk = pretty_hotkey(paths.settings.get("dictation_hotkey"))
        col = {"idle": T.SUCCESS, "listening": T.DANGER, "transcribing": T.WARN}.get(st, T.SUCCESS)
        self.badge.setStyleSheet(f"background: rgba(255,255,255,18); border-radius: 18px;")
        self.badge.setPixmap(T.pixmap("mic", col, 27))
        self.state.setText({"idle": "Ready", "listening": "Listening…", "transcribing": "Writing…"}.get(st, st))
        self.hint.setText(f"Click into any text box, press {hk}, speak, then press {hk} again."
                          if st == "idle" else f"Press {hk} again to finish." if st == "listening" else "")

    def add_history(self, text: str):
        if text:
            self.hist.insertItem(0, text)

    def _tick(self):
        lv = 0.0
        d = self.win.dictation
        if d.recording:
            lv = d.rec.level
        elif self._rec is not None:
            lv = self._rec.level
        self.level.setValue(int(min(1.0, lv * 12) * 100))

    def _local_toggle(self, on):
        if on:
            self._rec = voice_input.MicRecorder()
            try:
                self._rec.start()
                self.dict_btn.setText("Stop")
                self.set_state("listening")
            except Exception as e:  # noqa: BLE001
                self.dict_btn.setChecked(False)
                error_box(self, f"Microphone error: {e}")
        else:
            self.dict_btn.setText("Dictate")
            audio = self._rec.stop() if self._rec else None
            self._rec = None
            if audio is None or len(audio) < 4000:
                self.set_state("idle")
                return
            self.set_state("transcribing")
            from ..engines import textproc

            def job():
                t = textproc.clean_dictation(stt.transcribe(audio))
                if paths.settings.get("dictation_polish"):
                    try:
                        t = ai.polish_dictation(t)
                    except Exception:
                        pass
                return t

            def done(t):
                self.set_state("idle")
                cur = self.box.textCursor()
                cur.insertText((" " if self.box.toPlainText() and not self.box.toPlainText().endswith((" ", "\n")) else "") + t)
                self.add_history(t)

            def fail(m):
                self.set_state("idle")
                error_box(self, m)
            run_bg(self, job, on_done=done, on_fail=fail)

    def _polish_box(self):
        t = self.box.toPlainText().strip()
        if not t:
            return
        run_bg(self, ai.polish_dictation, t, on_done=self.box.setPlainText, on_fail=lambda m: error_box(self, m))

    def _save(self):
        s = paths.settings
        s.update(dictation_enabled=self.enabled.isChecked(), dictation_hotkey=self.hotkey.text().strip(),
                 read_hotkey=self.read_hotkey.text().strip(), dictation_polish=self.polish.isChecked(),
                 stt_language=self.lang.currentData(), stt_model=self.model.value())
        s.save()
        ok = self.win.dictation.start_hotkeys()
        self.set_state("idle")
        self.win.toast("Voice typing settings saved" if ok else "Hotkey couldn't be registered", "ok" if ok else "err")


# ===================================================================== PODCASTS
class PodcastsPage(Page):
    def __init__(self, win):
        super().__init__("AI podcasts", "Turn a document, a link or just an idea into a two-host podcast episode.")
        self.win = win
        from ..engines import podcast
        self.podcast = podcast
        c, v = card()
        g = QGridLayout()
        g.setVerticalSpacing(10)
        self.src = QComboBox()
        self.src.setMinimumWidth(380)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("Optional: a topic or angle, e.g. 'Explain malaria treatment for nurses'")
        self.topic.setMinimumWidth(380)
        self.style = Segmented(list(ai.STYLES), "Friendly chat")
        self.length = Segmented(["3 min", "5 min", "10 min", "15 min"], "5 min")
        self.host_a = QLineEdit("Amara")
        self.host_b = QLineEdit("Daniel")
        for w in (self.host_a, self.host_b):
            w.setFixedWidth(140)
        self.voice_a = QComboBox()
        self.voice_b = QComboBox()
        ha = QHBoxLayout()
        ha.addWidget(self.host_a)
        ha.addWidget(self.voice_a)
        hb = QHBoxLayout()
        hb.addWidget(self.host_b)
        hb.addWidget(self.voice_b)
        wa, wb = QWidget(), QWidget()
        wa.setLayout(ha)
        wb.setLayout(hb)
        ha.setContentsMargins(0, 0, 0, 0)
        hb.setContentsMargins(0, 0, 0, 0)
        form(g, 0, "From", self.src)
        form(g, 1, "Topic", self.topic)
        form(g, 2, "Style", self.style)
        form(g, 3, "Length", self.length)
        form(g, 4, "Host 1", wa)
        form(g, 5, "Host 2", wb)
        g.setColumnStretch(2, 1)
        v.addLayout(g)
        go = button("Create podcast", "podcast", "primary")
        go.clicked.connect(self.create)
        v.addWidget(go, 0, Qt.AlignLeft)
        self.busy = Busy()
        v.addWidget(self.busy)
        self.body.addWidget(c)
        self.body.addWidget(label("Your podcasts", "h2"))
        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        self.list.itemDoubleClicked.connect(lambda it: self._play(it.data(Qt.UserRole)))
        self.body.addWidget(self.list)
        row = QHBoxLayout()
        for text, ic, fn in (("Play", "play", self._play), ("Stop", "stop", lambda _i: win.audio.stop()),
                             ("Read script", "book", lambda i: win.open_item(i, False)),
                             ("Show file", "folder", lambda i: open_path(i.extra.get("audio", ""), True)),
                             ("Delete", "trash", self._delete)):
            b = button(text, ic, "primary" if text == "Play" else "")
            b.clicked.connect(lambda _=False, fn=fn: self._sel(fn))
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(label("Scripts are written by the AI brain (Settings); voices come from Voices.", "faint"))
        self.finish()
        self.refresh()

    def refresh(self):
        cur = self.src.currentData()
        self.src.clear()
        self.src.addItem("Only the topic below (no document)", None)
        for it in library.all_items({"doc", "web", "scan", "text", "note", "meeting"}):
            self.src.addItem(f"{library.KINDS.get(it.kind, '')}: {it.title[:70]}", it.id)
        i = self.src.findData(cur)
        self.src.setCurrentIndex(max(0, i))
        voices = tts.all_voices()
        for k, combo in enumerate((self.voice_a, self.voice_b)):
            sel = combo.currentData()
            combo.clear()
            for vv in voices:
                combo.addItem(vv.label, vv.id)
            j = combo.findData(sel)
            if j < 0:
                pref = ["kokoro:af_heart", "kokoro:am_michael"][k]
                j = max(0, combo.findData(pref) if combo.findData(pref) >= 0 else min(k, combo.count() - 1))
            combo.setCurrentIndex(j)
        self.list.clear()
        for it in library.all_items({"podcast"}):
            d = it.extra.get("duration", 0)
            li = QListWidgetItem(T.icon("podcast", T.KIND_COLORS["podcast"], 22),
                                 f"{it.title}\n{it.extra.get('style', '')} · {int(d // 60)}:{int(d % 60):02d} · "
                                 f"{' & '.join(it.extra.get('hosts', []))}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)

    def _sel(self, fn):
        it = self.list.currentItem()
        if it:
            fn(it.data(Qt.UserRole))

    def _play(self, item):
        p = item.extra.get("audio")
        if p and Path(p).exists():
            self.win.audio.play_file(p, item.title)

    def _delete(self, item):
        if QMessageBox.question(self, "Delete", f"Delete '{item.title}'?") == QMessageBox.Yes:
            library.delete(item)
            self.refresh()

    def create(self):
        sid = self.src.currentData()
        topic = self.topic.text().strip()
        src_item = library.load(sid) if sid else None
        if not src_item and not topic:
            self.win.toast("Choose a document or type a topic", "err")
            return
        a, b = self.host_a.text().strip() or "Amara", self.host_b.text().strip() or "Daniel"
        if a.lower() == b.lower():
            b += " 2"
        va, vb = self.voice_a.currentData(), self.voice_b.currentData()
        if not va or not vb:
            self.win.toast("Install a voice first (Voices)", "err")
            return
        minutes = int(self.length.value().split()[0])
        title = src_item.title if src_item else topic
        self.busy.start("Writing the script…")

        def done(item):
            self.busy.done()
            self.refresh()
            self.win.toast("Your podcast is ready", "ok")
            self._play(item)

        def fail(m):
            self.busy.done()
            error_box(self, m, "Podcast")
        run_bg(self, self.podcast.create, src_item.text if src_item else "", topic, self.style.value(), minutes,
               a, b, va, vb, title, on_done=done, on_fail=fail, on_progress=self.busy.update_)


# ===================================================================== MEETINGS
class MeetingsPage(Page):
    def __init__(self, win):
        super().__init__("Meeting notes", "Record a meeting or call: get a transcript, summary, decisions and action "
                                          "items, then ask questions about it.")
        self.win = win
        self.rec = voice_input.MeetingRecorder()
        c, v = card()
        h = QHBoxLayout()
        self.rec_btn = button("Start recording", "mic", "primary")
        self.rec_btn.clicked.connect(self.toggle)
        self.timer_lbl = label("00:00", "h1")
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setFixedWidth(200)
        self.sys = QCheckBox("Also record computer audio (Zoom, Meet, Teams…)")
        self.sys.setChecked(True)
        imp = button("Import recording", "upload")
        imp.clicked.connect(self._import)
        h.addWidget(self.rec_btn)
        h.addWidget(self.timer_lbl)
        h.addWidget(self.level)
        h.addStretch(1)
        h.addWidget(imp)
        v.addLayout(h)
        v.addWidget(self.sys)
        v.addWidget(label("Tell everyone when you're recording.", "faint"))
        self.busy = Busy()
        v.addWidget(self.busy)
        self.body.addWidget(c)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        self.list.currentItemChanged.connect(lambda it, _p: it and self._show(it.data(Qt.UserRole)))
        split.addWidget(self.list)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.tabs = QTabWidget()
        self.notes = QTextBrowser()
        self.transcript = QTextBrowser()
        self.tabs.addTab(self.notes, "Notes")
        self.tabs.addTab(self.transcript, "Transcript")
        rv.addWidget(self.tabs, 1)
        ar = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Ask about this meeting… e.g. What did we decide about the budget?")
        self.q.returnPressed.connect(self._ask)
        ask = button("Ask", "send")
        ask.clicked.connect(self._ask)
        listen = button("Listen to notes", "volume")
        listen.clicked.connect(lambda: self.win.mini_read("Meeting notes", self.notes.toPlainText()))
        ar.addWidget(self.q, 1)
        ar.addWidget(ask)
        ar.addWidget(listen)
        rv.addLayout(ar)
        split.addWidget(right)
        split.setSizes([280, 700])
        split.setMinimumHeight(440)
        self.body.addWidget(split)
        self.finish()
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)
        self.t.start(200)
        self.current: library.Item | None = None
        self.refresh()

    def refresh(self):
        self.list.clear()
        for it in library.all_items({"meeting"}):
            d = it.extra.get("duration", 0)
            li = QListWidgetItem(T.icon("meeting", T.KIND_COLORS["meeting"], 20),
                                 f"{it.title}\n{int(d // 60)} min · {time.strftime('%d %b %H:%M', time.localtime(it.created))}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)

    def _show(self, it):
        self.current = it
        self.notes.setMarkdown(it.extra.get("notes", ""))
        self.transcript.setPlainText(it.text)

    def _tick(self):
        if self.rec.running:
            s = int(self.rec.elapsed())
            self.timer_lbl.setText(f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}")
            self.level.setValue(int(min(1.0, self.rec.level * 10) * 100))
            if self.rec.sys_error:
                self.win.toast(f"Computer audio unavailable ({self.rec.sys_error[:60]}) - recording mic only", "info")
                self.rec.sys_error = ""

    def toggle(self):
        if not self.rec.running:
            try:
                self.rec.start(self.sys.isChecked())
            except Exception as e:  # noqa: BLE001
                error_box(self, f"Couldn't start recording: {e}")
                return
            self.rec_btn.setText("Stop & make notes")
            self.rec_btn.setIcon(T.icon("stop", "#0B0D12", 18))
            self.sys.setEnabled(False)
        else:
            path = self.rec.stop()
            self.rec_btn.setText("Start recording")
            self.rec_btn.setIcon(T.icon("mic", "#0B0D12", 18))
            self.sys.setEnabled(True)
            self.level.setValue(0)
            self._process(str(path))

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Meeting recording", "", "Audio/Video (*.wav *.mp3 *.m4a *.ogg "
                                           "*.flac *.mp4 *.webm *.aac);;All files (*)")
        if f:
            self._process(f)

    def _process(self, path):
        title, ok = QInputDialog.getText(self, "Meeting", "Meeting name:", text=Path(path).stem)
        self.busy.start("Transcribing…")

        def done(item):
            self.busy.done()
            self.refresh()
            self.list.setCurrentRow(0)
            self.win.library_changed()
            self.win.toast("Meeting notes ready", "ok")

        def fail(m):
            self.busy.done()
            error_box(self, m, "Meeting notes")
        run_bg(self, voice_input.process_meeting, path, title if ok and title.strip() else "",
               on_done=done, on_fail=fail, on_progress=self.busy.update_)

    def _ask(self):
        q = self.q.text().strip()
        if not q or not self.current:
            return
        self.q.clear()
        it = self.current
        src = [(it.title, (it.extra.get("notes", "") + "\n\n" + it.text))]
        self.busy.start("Thinking…")

        def done(ans):
            self.busy.done()
            self.tabs.setCurrentIndex(0)
            self.notes.append(f"\n\n**Q: {q}**\n\n{ans}")
            self.notes.setMarkdown(self.notes.toMarkdown())
        run_bg(self, ai.ask, q, src, on_done=done, on_fail=lambda m: (self.busy.done(), error_box(self, m)))


# ===================================================================== NOTES
class NotesPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.current: library.Item | None = None
        self._dirty = False
        h = QHBoxLayout(self)
        h.setContentsMargins(28, 24, 28, 20)
        h.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label("Notes", "h1"))
        new = button("New note", "plus", "primary")
        new.clicked.connect(self.new_note)
        left.addWidget(new)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes…")
        self.search.textChanged.connect(self.refresh)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.list.currentItemChanged.connect(lambda it, _p: it and self._open(it.data(Qt.UserRole)))
        left.addWidget(self.list, 1)
        h.addLayout(left)
        right = QVBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title")
        self.title.setStyleSheet("font-size: 20px; font-weight: 700; padding: 10px;")
        self.title.textEdited.connect(self._edited)
        right.addWidget(self.title)
        tb = QHBoxLayout()
        self.dict_btn = button("Dictate", "mic")
        self.dict_btn.setCheckable(True)
        self.dict_btn.toggled.connect(self._dictate)
        pol = button("AI polish", "spark", tip="Turn rough dictation into a clean, organised note")
        pol.clicked.connect(self._polish)
        lis = button("Listen", "play")
        lis.clicked.connect(lambda: self.current and (self._flush(), self.win.open_item(self.current, True)))
        ask = button("Ask across my documents", "chat", "ghost")
        ask.clicked.connect(lambda: win.go("ask"))
        dele = button("", "trash", "ghost", "Delete note")
        dele.clicked.connect(self._delete)
        for w in (self.dict_btn, pol, lis):
            tb.addWidget(w)
        tb.addStretch(1)
        tb.addWidget(ask)
        tb.addWidget(dele)
        right.addLayout(tb)
        self.busy = Busy()
        right.addWidget(self.busy)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Start typing, or press Dictate and just talk…")
        self.edit.setStyleSheet("QPlainTextEdit { font-size: 16px; padding: 18px; }")
        self.edit.textChanged.connect(self._edited)
        right.addWidget(self.edit, 1)
        h.addLayout(right, 1)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._flush)
        self._rec = None
        self.refresh()

    def refresh(self, *_):
        cur = self.current.id if self.current else None
        self.list.blockSignals(True)
        self.list.clear()
        for it in library.all_items({"note"}, self.search.text()):
            li = QListWidgetItem(f"{it.title or 'Untitled'}\n{time.strftime('%d %b %H:%M', time.localtime(it.updated))}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)
            if it.id == cur:
                self.list.setCurrentItem(li)
        self.list.blockSignals(False)

    def new_note(self):
        self._flush()
        it = library.save(library.Item("note", "Untitled note", ""))
        self.current = None
        self.refresh()
        self._open(it)
        self.list.setCurrentRow(0)
        self.edit.setFocus()

    def _open(self, it):
        self._flush()
        self.current = it
        self.title.blockSignals(True)
        self.edit.blockSignals(True)
        self.title.setText(it.title)
        self.edit.setPlainText(it.text)
        self.title.blockSignals(False)
        self.edit.blockSignals(False)
        self._dirty = False

    def _edited(self, *_):
        if self.current:
            self._dirty = True
            self.save_timer.start(800)

    def _flush(self):
        if self.current and self._dirty:
            self.current.title = self.title.text().strip() or "Untitled note"
            self.current.text = self.edit.toPlainText()
            library.save(self.current)
            self._dirty = False

    def _dictate(self, on):
        if on:
            if not self.current:
                self.new_note()
            self._rec = voice_input.MicRecorder()
            try:
                self._rec.start()
                self.dict_btn.setText("Stop")
                self.busy.start("Listening… press Stop when you're done")
            except Exception as e:  # noqa: BLE001
                self.dict_btn.setChecked(False)
                error_box(self, f"Microphone error: {e}")
        else:
            self.dict_btn.setText("Dictate")
            audio = self._rec.stop() if self._rec else None
            self._rec = None
            if audio is None or len(audio) < 4000:
                self.busy.done()
                return
            self.busy.start("Writing…")
            from ..engines import textproc

            def done(t):
                self.busy.done()
                cur = self.edit.textCursor()
                prev = self.edit.toPlainText()
                cur.insertText(("" if not prev or prev.endswith(("\n", " ")) else " ") + t)
                if self.title.text() in ("", "Untitled note") and t:
                    self.title.setText(" ".join(t.split()[:6]).rstrip(".,"))
                self._edited()
            run_bg(self, lambda: textproc.clean_dictation(stt.transcribe(audio)), on_done=done,
                   on_fail=lambda m: (self.busy.done(), error_box(self, m)))

    def _polish(self):
        t = self.edit.toPlainText().strip()
        if not t:
            return
        self.busy.start("Polishing…")

        def done(res):
            self.busy.done()
            lines = res.strip().split("\n", 1)
            self.title.setText(lines[0].strip("# *").strip()[:80])
            self.edit.setPlainText(lines[1].strip() if len(lines) > 1 else res)
            self._edited()
        run_bg(self, ai.polish_note, t, on_done=done, on_fail=lambda m: (self.busy.done(), error_box(self, m)))

    def _delete(self):
        if self.current and QMessageBox.question(self, "Delete", "Delete this note?") == QMessageBox.Yes:
            library.delete(self.current)
            self.current = None
            self.title.clear()
            self.edit.clear()
            self.refresh()


# ===================================================================== VOICES
class VoicesPage(Page):
    def __init__(self, win):
        super().__init__("Voices", "Natural voices that work offline. Add more languages, or clone your own voice.")
        self.win = win
        c, v = card()
        v.addWidget(label("Installed voices", "h2"))
        self.list = QListWidget()
        self.list.setMinimumHeight(300)
        v.addWidget(self.list)
        row = QHBoxLayout()
        pv = button("Preview", "play")
        pv.clicked.connect(self._preview)
        df = button("Use as default", "check", "primary")
        df.clicked.connect(self._default)
        self.sample = QLineEdit("Hello! This is how I sound when I read to you.")
        row.addWidget(df)
        row.addWidget(pv)
        row.addWidget(self.sample, 1)
        v.addLayout(row)
        self.body.addWidget(c)

        c2, v2 = card()
        v2.addWidget(label("Get more voices: 40+ languages (internet needed once)", "h2"))
        v2.addWidget(label("Piper voices: fast, offline after download (~20-60 MB each). Includes Swahili, French, "
                           "Arabic, Portuguese, Hindi, Chinese, German, Russian and more.", "muted", True))
        r2 = QHBoxLayout()
        load = button("Browse voice catalogue", "voice")
        load.clicked.connect(self._catalog)
        self.cfilter = QLineEdit()
        self.cfilter.setPlaceholderText("Filter by language, e.g. Swahili")
        self.cfilter.textChanged.connect(self._filter)
        r2.addWidget(load)
        r2.addWidget(self.cfilter, 1)
        v2.addLayout(r2)
        self.cat = QListWidget()
        self.cat.setMinimumHeight(200)
        self.cat.hide()
        v2.addWidget(self.cat)
        inst = button("Install selected voice", "download")
        inst.clicked.connect(self._install)
        inst.hide()
        self.inst_btn = inst
        v2.addWidget(inst, 0, Qt.AlignLeft)
        self.busy = Busy()
        v2.addWidget(self.busy)
        self.body.addWidget(c2)

        c3, v3 = card()
        v3.addWidget(label("Clone your voice", "h2"))
        from ..engines import tts as _t
        if _t.ENGINES["clone"].available():
            v3.addWidget(label("Add 1-3 clear recordings of YOUR voice (10-30 s each, quiet room). Reading in a "
                               "cloned voice is slower on a CPU.", "muted", True))
            r3 = QHBoxLayout()
            rec = button("Record 20 seconds", "mic", "primary")
            rec.clicked.connect(self._record_clone)
            fl = button("Use recordings…", "upload")
            fl.clicked.connect(self._files_clone)
            r3.addWidget(rec)
            r3.addWidget(fl)
            r3.addStretch(1)
            v3.addLayout(r3)
        else:
            v3.addWidget(label("Voice cloning is an optional component. Rebuild with  build.bat clone  to add it "
                               "(about 3 GB extra).", "muted", True))
        v3.addWidget(label("Only clone your own voice, or one you have clear permission to use.", "faint", True))
        self.body.addWidget(c3)
        self.finish()
        self.catalog: list[dict] = []
        self.refresh()

    def refresh(self):
        self.list.clear()
        default = paths.settings.get("voice")
        for vv in tts.all_voices():
            li = QListWidgetItem(T.icon("voice", T.ACCENT if vv.engine == "kokoro" else T.ACCENT2, 20),
                                 ("★ " if vv.id == default else "") + vv.label)
            li.setData(Qt.UserRole, vv.id)
            self.list.addItem(li)
        if not self.list.count():
            self.list.addItem("No voices installed yet: run build.bat, or install one below.")

    def _vid(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _preview(self):
        vid = self._vid()
        if vid:
            self.win.mini_read("Voice preview", self.sample.text() or "Hello!", voice=vid)

    def _default(self):
        vid = self._vid()
        if vid:
            paths.settings["voice"] = vid
            paths.settings.save()
            self.win.voices_changed()
            self.win.pages["reader"].reader.set_voice(vid)
            self.win.toast("Default voice set", "ok")

    def _catalog(self):
        self.busy.start("Loading catalogue…")

        def done(cat):
            self.busy.done()
            self.catalog = cat
            self.cat.show()
            self.inst_btn.show()
            self._filter()

        def fail(m):
            self.busy.done()
            error_box(self, f"Couldn't load the voice catalogue (internet needed).\n\n{m}")
        run_bg(self, tts.piper_catalog, on_done=done, on_fail=fail)

    def _filter(self, *_):
        q = self.cfilter.text().lower().strip()
        self.cat.clear()
        for e in self.catalog:
            if q and q not in e["language"].lower() and q not in e["name"].lower():
                continue
            li = QListWidgetItem(f"{e['language']} · {e['name'].replace('_', ' ').title()} ({e['quality']}) · {e['size_mb']} MB")
            li.setData(Qt.UserRole, e)
            self.cat.addItem(li)

    def _install(self):
        it = self.cat.currentItem()
        if not it:
            return
        e = it.data(Qt.UserRole)
        self.busy.start(f"Installing {e['name']}…")

        def done(_):
            self.busy.done()
            self.win.voices_changed()
            self.win.toast(f"Voice {e['name']} installed", "ok")
        run_bg(self, tts.install_piper_voice, e, on_done=done,
               on_fail=lambda m: (self.busy.done(), error_box(self, m)), on_progress=self.busy.update_)

    def _record_clone(self):
        name, ok = QInputDialog.getText(self, "Clone your voice", "Name for this voice:", text="My voice")
        if not ok or not name.strip():
            return
        QMessageBox.information(self, "Recording", "After you click OK, read anything aloud for 20 seconds in a "
                                                   "natural voice (a paragraph from a book works well).")
        rec = voice_input.MicRecorder(sr=24000)
        try:
            rec.start()
        except Exception as e:  # noqa: BLE001
            error_box(self, f"Microphone error: {e}")
            return
        self.busy.start("Recording… keep talking")
        t0 = time.time()

        def tick():
            el = time.time() - t0
            self.busy.update_(min(1.0, el / 20), f"Recording… {int(20 - el)} s left")
            if el >= 20:
                timer.stop()
                audio = rec.stop()
                from ..engines import audio_io
                tmp = paths.sub("Audio") / f"clone_{int(t0)}.wav"
                audio_io.save_audio(tmp, audio, 24000, fmt="wav")
                self._save_clone(name, [str(tmp)])
        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(200)
        self._clone_timer = timer

    def _files_clone(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Recordings of your voice", "", "Audio (*.wav *.mp3 *.m4a *.flac *.ogg)")
        if fs:
            name, ok = QInputDialog.getText(self, "Clone your voice", "Name for this voice:", text="My voice")
            if ok and name.strip():
                self._save_clone(name, fs)

    def _save_clone(self, name, files):
        from ..engines import voiceclone
        try:
            voiceclone.save_voice(name, files)
        except Exception as e:  # noqa: BLE001
            error_box(self, str(e))
            return
        self.busy.done()
        self.win.voices_changed()
        self.win.toast(f"Voice '{name}' created", "ok")


# ===================================================================== SETTINGS
class SettingsPage(Page):
    def __init__(self, win):
        super().__init__("Settings", "")
        self.win = win
        s = paths.settings
        c, v = card()
        v.addWidget(label("AI brain", "h2"))
        v.addWidget(label("Powers summaries, answers, quizzes, podcasts and meeting notes. Offline works with no "
                          "internet; online is faster and smarter.", "muted", True))
        g = QGridLayout()
        g.setVerticalSpacing(10)
        self.mode = Segmented(["Auto", "Offline", "Online"], s.get("ai_mode", "Auto"),
                              {"Auto": "Online when available, otherwise offline"})
        self.provider = QComboBox()
        self.provider.addItems(list(llm.PROVIDERS))
        self.provider.setCurrentText(s.get("ai_provider", "Google Gemini"))
        self.provider.currentTextChanged.connect(self._prov)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Paste your API key")
        self.key.setMinimumWidth(380)
        self.getkey = button("Get a free key", "link", "ghost")
        self.getkey.clicked.connect(self._open_key_page)
        self.model = QLineEdit(s.get("ai_model", ""))
        self.model.setMinimumWidth(260)
        self.base = QLineEdit(s.get("ai_base_url", ""))
        self.base.setPlaceholderText("http://localhost:1234/v1 (custom only)")
        self.base.setMinimumWidth(380)
        krow = QHBoxLayout()
        krow.addWidget(self.key)
        krow.addWidget(self.getkey)
        kw = QWidget()
        kw.setLayout(krow)
        krow.setContentsMargins(0, 0, 0, 0)
        form(g, 0, "Mode", self.mode)
        form(g, 1, "Online provider", self.provider)
        form(g, 2, "API key", kw)
        form(g, 3, "Model", self.model, label("leave empty for the default", "faint"))
        form(g, 4, "Custom URL", self.base)
        self.local_lbl = label("", "faint", True)
        lm = button("Choose model file (.gguf)", "folder", "ghost")
        lm.clicked.connect(self._pick_gguf)
        lw = QHBoxLayout()
        lw.addWidget(self.local_lbl, 1)
        lw.addWidget(lm)
        lww = QWidget()
        lww.setLayout(lw)
        lw.setContentsMargins(0, 0, 0, 0)
        form(g, 5, "Offline model", lww)
        g.setColumnStretch(2, 1)
        v.addLayout(g)
        r = QHBoxLayout()
        sv = button("Save", "check", "primary")
        sv.clicked.connect(self._save_ai)
        test = button("Test AI", "spark")
        test.clicked.connect(self._test)
        r.addWidget(sv)
        r.addWidget(test)
        r.addStretch(1)
        v.addLayout(r)
        self.test_out = label("", "muted", True)
        v.addWidget(self.test_out)
        self.body.addWidget(c)
        self._prov(self.provider.currentText())

        c2, v2 = card()
        v2.addWidget(label("Reading", "h2"))
        self.skip = QCheckBox("Skip citations like [12] and (Smith, 2020), and read web links as 'link'")
        self.skip.setChecked(bool(s.get("skip_citations", True)))
        self.skip.toggled.connect(self._reading)
        v2.addWidget(self.skip)
        self.body.addWidget(c2)

        c3, v3 = card()
        v3.addWidget(label("Browser extension: listen to any web page", "h2"))
        v3.addWidget(label("Chrome / Edge / Brave: open chrome://extensions → turn on Developer mode → Load unpacked "
                           "→ choose the 'extension' folder. Then click the ReadRush icon on any page (or Alt+Shift+L).",
                           "muted", True))
        eb = button("Open extension folder", "folder")
        eb.clicked.connect(lambda: open_path(paths.EXTENSION_DIR))
        v3.addWidget(eb, 0, Qt.AlignLeft)
        self.body.addWidget(c3)

        c4, v4 = card()
        v4.addWidget(label("Storage", "h2"))
        row = QHBoxLayout()
        self.data = QLineEdit(str(paths.data_root()))
        self.data.setReadOnly(True)
        ch = button("Change", "folder")
        ch.clicked.connect(self._pick_data)
        op = button("Open", "folder", "ghost")
        op.clicked.connect(lambda: open_path(paths.data_root()))
        row.addWidget(self.data, 1)
        row.addWidget(ch)
        row.addWidget(op)
        v4.addLayout(row)
        from .. import __version__
        v4.addWidget(label(f"ReadRush {__version__} · Voices: Kokoro-82M (Apache-2.0), Piper (MIT; voice licences vary) · "
                           "Speech recognition: Whisper (MIT) via faster-whisper · OCR: RapidOCR/PaddleOCR (Apache-2.0) "
                           "· Offline AI: llama.cpp (MIT) + Qwen (Apache-2.0)", "faint", True))
        self.body.addWidget(c4)
        self.finish()
        self._local_info()

    def _prov(self, name):
        kind, base, model, url = llm.PROVIDERS.get(name, ("", "", "", ""))
        self.key.setText((paths.settings.get("ai_keys") or {}).get(name, ""))
        self.model.setPlaceholderText(model or "model name")
        self.base.setEnabled(name.startswith("Custom"))
        self.getkey.setVisible(bool(url))
        self.getkey.setText("Get a free key" if name in ("Google Gemini", "Groq") else "Get a key")

    def _open_key_page(self):
        url = llm.PROVIDERS.get(self.provider.currentText(), ("", "", "", ""))[3]
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _save_ai(self):
        s = paths.settings
        keys = dict(s.get("ai_keys") or {})
        keys[self.provider.currentText()] = self.key.text().strip()
        s.update(ai_mode=self.mode.value(), ai_provider=self.provider.currentText(), ai_keys=keys,
                 ai_model=self.model.text().strip(), ai_base_url=self.base.text().strip())
        s.save()
        self.win.ai_changed()
        self.win.toast("AI settings saved", "ok")

    def _test(self):
        self._save_ai()
        self.test_out.setText("Testing…")
        t0 = time.time()
        run_bg(self, lambda: llm.chat([{"role": "user", "content": "Say hello in five words."}], max_tokens=30),
               on_done=lambda r: self.test_out.setText(f"✔ {llm.describe()} replied in {time.time() - t0:.1f}s: {r}"),
               on_fail=lambda m: self.test_out.setText("✘ " + m.split("\n\n")[0]))

    def _local_info(self):
        m = llm.LOCAL.model()
        exe = llm.LOCAL.exe()
        self.local_lbl.setText(f"{m.name} ({m.stat().st_size / 1e9:.1f} GB)" if m and exe
                               else "Not installed: run build.bat (or choose a .gguf file)")

    def _pick_gguf(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a GGUF model", str(paths.GGUF_DIR), "GGUF model (*.gguf)")
        if f:
            paths.settings["local_model"] = f
            paths.settings.save()
            llm.LOCAL.stop()
            self._local_info()

    def _reading(self, on):
        paths.settings["skip_citations"] = on
        paths.settings.save()
        self.win.pages["reader"].reader.skip_citations = on

    def _pick_data(self):
        d = QFileDialog.getExistingDirectory(self, "Store ReadRush files in", str(paths.data_root()))
        if d:
            paths.settings["data_root"] = d
            paths.settings.save()
            self.data.setText(d)
            self.win.library_changed()
