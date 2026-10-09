"""The listening experience: document view with live sentence + word highlighting, player bar,
and an AI side panel (Summary, Ask, Quiz, Recap)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                               QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from .. import paths
from ..engines import ai, library, reader, textproc, tts
from . import theme as T
from .widgets import Busy, Segmented, button, error_box, label, run_bg


class _QtIndex:
    """Python str index -> QTextDocument position (characters outside the BMP count twice in Qt)."""

    def __init__(self, text: str):
        self.astral = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF]

    def __call__(self, i: int) -> int:
        if not self.astral:
            return i
        import bisect
        return i + bisect.bisect_left(self.astral, i)


class AIPanel(QFrame):
    def __init__(self, page: "ReaderPage"):
        super().__init__()
        self.page = page
        self.setObjectName("card")
        self.setFixedWidth(360)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("AI Assistant", "h2"), 1)
        self.brain = label("", "faint")
        head.addWidget(self.brain)
        v.addLayout(head)
        self.tabs = Segmented(["Summary", "Ask", "Quiz", "Recap"])
        self.tabs.changed.connect(self._tab)
        v.addWidget(self.tabs)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.busy = Busy()
        v.addWidget(self.busy)

        # --- summary
        w = QWidget()
        sv = QVBoxLayout(w)
        sv.setContentsMargins(0, 0, 0, 0)
        self.sum_len = Segmented(list(ai.LENGTHS), "Medium")
        sv.addWidget(self.sum_len)
        row = QHBoxLayout()
        b = button("Summarize", "spark", "primary")
        b.clicked.connect(self.summarize)
        self.sum_listen = button("Listen", "volume")
        self.sum_listen.clicked.connect(lambda: self.page.speak_text("Summary", self.sum_out.toPlainText()))
        row.addWidget(b)
        row.addWidget(self.sum_listen)
        sv.addLayout(row)
        self.sum_out = QTextBrowser()
        sv.addWidget(self.sum_out, 1)
        self.stack.addWidget(w)

        # --- ask
        w = QWidget()
        av = QVBoxLayout(w)
        av.setContentsMargins(0, 0, 0, 0)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        av.addWidget(self.chat, 1)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Ask about this document…")
        self.q.returnPressed.connect(self.ask)
        mic = button("", "mic", tip="Ask by voice (click, speak, click again)")
        mic.setCheckable(True)
        mic.toggled.connect(self._voice_q)
        self.mic = mic
        send = button("", "send", "primary")
        send.clicked.connect(self.ask)
        row.addWidget(self.q, 1)
        row.addWidget(mic)
        row.addWidget(send)
        av.addLayout(row)
        from PySide6.QtWidgets import QCheckBox
        self.speak_answers = QCheckBox("Read answers aloud")
        av.addWidget(self.speak_answers)
        self.history: list[dict] = []
        self.stack.addWidget(w)

        # --- quiz
        w = QWidget()
        qv = QVBoxLayout(w)
        qv.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.qn = QSpinBox()
        self.qn.setRange(3, 15)
        self.qn.setValue(5)
        row.addWidget(label("Questions", "muted"))
        row.addWidget(self.qn)
        gb = button("Make quiz", "quiz", "primary")
        gb.clicked.connect(self.make_quiz)
        row.addWidget(gb)
        qv.addLayout(row)
        self.quiz_area = QScrollArea()
        self.quiz_area.setWidgetResizable(True)
        self.quiz_inner = QWidget()
        self.quiz_box = QVBoxLayout(self.quiz_inner)
        self.quiz_box.addStretch(1)
        self.quiz_area.setWidget(self.quiz_inner)
        qv.addWidget(self.quiz_area, 1)
        self.check = button("Check answers", "check")
        self.check.clicked.connect(self.check_quiz)
        self.check.hide()
        self.score = label("", "h2")
        qv.addWidget(self.check)
        qv.addWidget(self.score)
        self.quiz_data: list = []
        self.quiz_groups: list = []
        self.stack.addWidget(w)

        # --- recap
        w = QWidget()
        rv = QVBoxLayout(w)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(label("Coming back to a reading? Get a quick recap of everything up to where you stopped.",
                           "muted", True))
        rb = button("Recap what I've read", "spark", "primary")
        rb.clicked.connect(self.recap)
        rv.addWidget(rb)
        self.recap_out = QTextBrowser()
        rv.addWidget(self.recap_out, 1)
        lb = button("Listen", "volume")
        lb.clicked.connect(lambda: self.page.speak_text("Recap", self.recap_out.toPlainText()))
        rv.addWidget(lb)
        self.stack.addWidget(w)
        self.refresh_brain()

    def refresh_brain(self):
        from ..engines import llm
        self.brain.setText(llm.describe())

    def _tab(self, name):
        self.stack.setCurrentIndex(["Summary", "Ask", "Quiz", "Recap"].index(name))

    def _fail(self, msg):
        self.busy.done()
        error_box(self, msg, "AI Assistant")

    # ---------------- actions
    def summarize(self):
        text = self.page.text
        if not text:
            return
        self.sum_out.clear()
        self.busy.start("Summarizing…")

        def done(res):
            self.busy.done()
            self.sum_out.setMarkdown(res)
            if self.page.item:
                self.page.item.extra["summary"] = res
                library.save(self.page.item)
        run_bg(self, ai.summarize, text, self.sum_len.value(), on_done=done, on_fail=self._fail,
               on_progress=self.busy.update_)

    def ask(self, question: str | None = None):
        q = (question or self.q.text()).strip()
        if not q or not self.page.text:
            return
        self.q.clear()
        self._append("You", q)
        self.busy.start("Thinking…")
        src = [(self.page.title, self.page.text)]
        hist = list(self.history)

        def done(ans):
            self.busy.done()
            self.history += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
            self._append("ReadRush", ans)
            if self.speak_answers.isChecked():
                self.page.speak_text("Answer", ans)
        run_bg(self, ai.ask, q, src, hist, on_done=done, on_fail=self._fail)

    def _append(self, who, text):
        import html
        color = T.ACCENT if who == "You" else T.ACCENT2
        body = html.escape(text).replace("\n", "<br>")
        self.chat.append(f"<p><b style='color:{color}'>{who}</b><br>{body}</p>")

    def _voice_q(self, on: bool):
        from ..engines import voice_input
        if on:
            self._rec = voice_input.MicRecorder()
            try:
                self._rec.start()
                self.mic.setIcon(T.icon("stop", T.DANGER, 18))
            except Exception as e:  # noqa: BLE001
                self.mic.setChecked(False)
                error_box(self, f"Microphone error: {e}")
        else:
            self.mic.setIcon(T.icon("mic", T.TEXT, 18))
            audio = self._rec.stop()
            self.busy.start("Listening to your question…")
            from ..engines import stt

            def done(text):
                self.busy.done()
                if text.strip():
                    self.speak_answers.setChecked(True)
                    self.ask(text)
            run_bg(self, stt.transcribe, audio, on_done=done, on_fail=self._fail)

    def make_quiz(self):
        if not self.page.text:
            return
        self.busy.start("Writing your quiz…")
        run_bg(self, ai.quiz, self.page.text, self.qn.value(), on_done=self._show_quiz, on_fail=self._fail,
               on_progress=self.busy.update_)

    def _show_quiz(self, data):
        self.busy.done()
        while self.quiz_box.count() > 1:
            w = self.quiz_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.quiz_data, self.quiz_groups = data, []
        for i, q in enumerate(data):
            f = QFrame()
            f.setObjectName("card2")
            fv = QVBoxLayout(f)
            fv.addWidget(label(f"{i + 1}. {q['question']}", "", True))
            g = QButtonGroup(f)
            for k, o in enumerate(q["options"]):
                rb = QRadioButton(o)
                g.addButton(rb, k)
                fv.addWidget(rb)
            fb = label("", "faint", True)
            fv.addWidget(fb)
            self.quiz_groups.append((g, fb))
            self.quiz_box.insertWidget(self.quiz_box.count() - 1, f)
        self.check.show()
        self.score.setText("")

    def check_quiz(self):
        right = 0
        for q, (g, fb) in zip(self.quiz_data, self.quiz_groups):
            ok = g.checkedId() == q["answer"]
            right += ok
            fb.setText(("✔ Correct. " if ok else f"✘ Answer: {q['options'][q['answer']]}. ") + q.get("explanation", ""))
            fb.setStyleSheet(f"color: {T.SUCCESS if ok else T.DANGER};")
        self.score.setText(f"Score: {right}/{len(self.quiz_data)}")

    def recap(self):
        upto = self.page.text_read()
        if not upto.strip():
            self.recap_out.setPlainText("Start listening first - the recap covers what you've read so far.")
            return
        self.busy.start("Recapping…")

        def done(res):
            self.busy.done()
            self.recap_out.setPlainText(res)
        run_bg(self, ai.recap, upto, on_done=done, on_fail=self._fail)


class ReaderPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("page")
        self.reader = reader.Reader()
        self.reader.speed = float(paths.settings.get("speed", 1.0))
        self.reader.skip_citations = bool(paths.settings.get("skip_citations", True))
        self.item: library.Item | None = None
        self.title = ""
        self.text = ""
        self.qi = _QtIndex("")
        self._last_hl = None
        self._resume_item: library.Item | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 14)
        root.setSpacing(12)
        head = QHBoxLayout()
        self.h_title = label("Nothing open", "h1")
        self.h_title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.h_meta = label("", "faint")
        tv = QVBoxLayout()
        tv.setSpacing(2)
        tv.addWidget(self.h_title)
        tv.addWidget(self.h_meta)
        head.addLayout(tv, 1)
        self.font_minus = button("A−", None, "ghost", "Smaller text")
        self.font_plus = button("A+", None, "ghost", "Bigger text")
        self.font_minus.clicked.connect(lambda: self._font(-1))
        self.font_plus.clicked.connect(lambda: self._font(1))
        self.theme = Segmented(list(T.READER_THEMES), paths.settings.get("reader_theme", "Dark"))
        self.theme.changed.connect(self._theme)
        exp = button("Save as MP3", "download", tip="Download the whole document as an audiobook")
        exp.clicked.connect(self.export_mp3)
        self.ai_btn = button("AI Assistant", "spark")
        self.ai_btn.setCheckable(True)
        self.ai_btn.setChecked(True)
        for w in (self.font_minus, self.font_plus, self.theme, exp, self.ai_btn):
            head.addWidget(w)
        root.addLayout(head)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.viewport().setCursor(Qt.PointingHandCursor)
        self.view.setToolTip("Click any sentence to start reading from there")
        self.view.viewport().installEventFilter(self)
        mid.addWidget(self.view, 1)
        self.panel = AIPanel(self)
        self.ai_btn.toggled.connect(self.panel.setVisible)
        mid.addWidget(self.panel)
        root.addLayout(mid, 1)

        # ---------------- player bar
        bar = QFrame()
        bar.setObjectName("card")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(16, 10, 16, 10)
        bh.setSpacing(10)
        self.prev = button("", "back", "ghost", "Previous sentence")
        self.prev.clicked.connect(lambda: self.reader.skip(-1))
        self.play = QPushButton()
        self.play.setObjectName("round")
        self.play.setCursor(Qt.PointingHandCursor)
        self.play.setIcon(T.icon("play", "#0B0D12", 20))
        self.play.clicked.connect(self.toggle)
        self.next = button("", "forward", "ghost", "Next sentence")
        self.next.clicked.connect(lambda: self.reader.skip(1))
        self.pos = label("", "muted")
        self.pos.setMinimumWidth(170)
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(5, 40)
        self.speed.setValue(int(round(self.reader.speed * 10)))
        self.speed.setFixedWidth(170)
        self.speed_lbl = label(f"{self.reader.speed:.1f}×", "pill")
        self.speed.valueChanged.connect(lambda v: self.speed_lbl.setText(f"{v / 10:.1f}×"))
        self.speed.sliderReleased.connect(self._speed)
        self.voice = QComboBox()
        self.voice.setMinimumWidth(230)
        self.voice.currentIndexChanged.connect(self._voice)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(80)
        self.vol.valueChanged.connect(lambda v: setattr(self.reader.player, "volume", v / 100))
        for w in (self.prev, self.play, self.next, self.pos):
            bh.addWidget(w)
        bh.addStretch(1)
        bh.addWidget(label("Speed", "faint"))
        bh.addWidget(self.speed)
        bh.addWidget(self.speed_lbl)
        bh.addSpacing(8)
        bh.addWidget(self.voice)
        bh.addWidget(QLabel_icon("volume"))
        bh.addWidget(self.vol)
        root.addWidget(bar)

        self.refresh_voices()
        self._apply_style()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)

    # ------------------------------------------------------------ content
    def open_item(self, item: library.Item, autoplay: bool = False):
        self._save_progress()
        self.item = item
        self._set_text(item.title, item.text)
        self.panel.sum_out.setMarkdown(item.extra.get("summary", ""))
        start = min(item.progress, max(0, len(self.reader.sentences) - 1))
        self.reader.last_index = start
        self._highlight(start, None)
        if autoplay:
            self.reader.play_from(start)

    def open_text(self, title: str, text: str, autoplay: bool = True):
        """Temporary text (selection hotkey, AI answers) - not saved to the library."""
        self._save_progress()
        self.item = None
        self._set_text(title, textproc.normalize_document(text))
        if autoplay:
            self.reader.play_from(0)

    def speak_text(self, title: str, text: str):
        if text.strip():
            self.win.mini_read(title, text)

    def _set_text(self, title: str, text: str):
        self.title, self.text = title, text
        self.reader.load(text)
        self.qi = _QtIndex(text)
        self.view.setPlainText(text)
        self.h_title.setText(title)
        mins = len(text.split()) / 170 / max(0.5, self.reader.speed)
        self.h_meta.setText(f"{len(text.split()):,} words · about {mins:.0f} min at {self.reader.speed:.1f}×")
        self.panel.history = []
        self.panel.chat.clear()
        self._last_hl = None
        self._apply_style()

    def text_read(self) -> str:
        if not self.reader.sentences:
            return ""
        i = self.reader.current_index()
        return self.text[: self.reader.sentences[i].end]

    def _save_progress(self):
        if self.item is not None:
            self.item.progress = self.reader.current_index()
            library.save(self.item)

    # ------------------------------------------------------------ transport
    def toggle(self):
        if not self.reader.sentences:
            self.win.go("library")
            return
        self.win.stop_mini()
        self.reader.toggle()
        if not self.reader.playing:
            self._save_progress()

    def _speed(self):
        v = self.speed.value() / 10
        paths.settings["speed"] = v
        paths.settings.save()
        self.reader.set_speed(v)
        if self.text:
            mins = len(self.text.split()) / 170 / v
            self.h_meta.setText(f"{len(self.text.split()):,} words · about {mins:.0f} min at {v:.1f}×")

    def refresh_voices(self):
        cur = self.reader.voice
        self.voice.blockSignals(True)
        self.voice.clear()
        for v in tts.all_voices():
            self.voice.addItem(v.label, v.id)
        if not self.voice.count():
            self.voice.addItem("No voices installed", None)
        i = self.voice.findData(cur)
        self.voice.setCurrentIndex(max(0, i))
        self.voice.blockSignals(False)
        if self.voice.currentData():
            self.reader.voice = self.voice.currentData()

    def _voice(self, _i):
        vid = self.voice.currentData()
        if vid:
            paths.settings["voice"] = vid
            paths.settings.save()
            self.reader.set_voice(vid)

    def export_mp3(self):
        if not self.text:
            return
        default = paths.sub("Audio") / f"{self.title[:60]}.mp3"
        f, _ = QFileDialog.getSaveFileName(self, "Save audiobook", str(default), "MP3 (*.mp3);;WAV (*.wav)")
        if not f:
            return
        self.win.run_task(f"Recording '{self.title[:40]}'", reader.render_to_file, self.text, self.reader.voice,
                          self.reader.speed, f, on_done=lambda p: self.win.toast(f"Saved {Path(p).name}", "ok"))

    # ------------------------------------------------------------ highlighting
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.view.viewport() and ev.type() == QEvent.MouseButtonRelease:
            QTimer.singleShot(0, lambda p=ev.position().toPoint(): self._click(p))
        return False

    def _click(self, point):
        if self.view.textCursor().hasSelection() or not self.reader.sentences:
            return
        pos = self.view.cursorForPosition(point).position()
        # Qt position -> python index (approx. fine for BMP text)
        for i, s in enumerate(self.reader.sentences):
            if s.start <= pos <= s.end + 1:
                self.win.stop_mini()
                self.reader.play_from(i)
                break

    def _tick(self):
        r = self.reader
        self.play.setIcon(T.icon("pause" if r.playing else "play", "#0B0D12", 20))
        if r.error:
            err, r.error = r.error, None
            error_box(self, f"Couldn't read aloud: {err}\n\nCheck the voice in Voices / Settings.")
        if r.finished and r.playing:
            r.pause()
            if self.item:
                self.item.progress = 0
                library.save(self.item)
        if not r.sentences:
            self.pos.setText("")
            return
        now = r.now() if r.playing or r.player.buffered() else None
        idx = now[0] if now else r.last_index
        self.pos.setText(f"Sentence {idx + 1:,}/{len(r.sentences):,} · {int(100 * (idx + 1) / len(r.sentences))}%")
        key = now if now else (idx, None, None)
        if key != self._last_hl and self.isVisible():
            self._highlight(idx, (now[1], now[2]) if now else None)
            self._last_hl = key

    def _highlight(self, idx: int, word: tuple[int, int] | None):
        if not self.reader.sentences:
            return
        s = self.reader.sentences[idx]
        bg, _fg, sent_col, word_col = T.READER_THEMES[self.theme.value()]
        sels = []
        sel = QTextEdit.ExtraSelection()
        c = QTextCursor(self.view.document())
        c.setPosition(self.qi(s.start))
        c.setPosition(self.qi(s.end), QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(sent_col) if not sent_col.startswith("rgba") else _rgba(sent_col))
        sel.cursor, sel.format = c, fmt
        sels.append(sel)
        if word and word[1] > word[0]:
            ws = QTextEdit.ExtraSelection()
            wc = QTextCursor(self.view.document())
            wc.setPosition(self.qi(word[0]))
            wc.setPosition(self.qi(word[1]), QTextCursor.KeepAnchor)
            wf = QTextCharFormat()
            wf.setBackground(QColor(word_col))
            wf.setForeground(QColor("#0B0D12"))
            ws.cursor, ws.format = wc, wf
            sels.append(ws)
        self.view.setExtraSelections(sels)
        # keep the spoken line comfortably in view
        rect = self.view.cursorRect(wc if word and word[1] > word[0] else c)
        vp = self.view.viewport().height()
        if rect.top() < vp * 0.15 or rect.bottom() > vp * 0.7:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.value() + rect.top() - int(vp * 0.35))

    # ------------------------------------------------------------ appearance
    def _font(self, d):
        size = max(11, min(34, int(paths.settings.get("reader_font_size", 17)) + d))
        paths.settings["reader_font_size"] = size
        paths.settings.save()
        self._apply_style()

    def _theme(self, name):
        paths.settings["reader_theme"] = name
        paths.settings.save()
        self._apply_style()
        self._last_hl = None

    def _apply_style(self):
        bg, fg, _s, _w = T.READER_THEMES[self.theme.value()]
        size = int(paths.settings.get("reader_font_size", 17))
        self.view.setStyleSheet(f"QTextEdit {{ background: {bg}; color: {fg}; border-radius: 16px; "
                                f"padding: 26px 34px; border: 1px solid {T.BORDER}; }}")
        f = QFont("Georgia", size)
        f.setStyleHint(QFont.Serif)
        self.view.setFont(f)
        doc = self.view.document()
        doc.setDocumentMargin(8)
        from PySide6.QtGui import QTextBlockFormat
        cur = QTextCursor(doc)
        cur.select(QTextCursor.Document)
        bf = QTextBlockFormat()
        bf.setLineHeight(165, 1)   # proportional line height (%)
        bf.setBottomMargin(size * 0.6)
        cur.mergeBlockFormat(bf)


def _rgba(s: str) -> QColor:
    nums = [float(x) for x in s[s.index("(") + 1: s.index(")")].split(",")]
    c = QColor(int(nums[0]), int(nums[1]), int(nums[2]))
    c.setAlphaF(nums[3])
    return c


def QLabel_icon(name: str) -> QLabel:
    lb = QLabel()
    lb.setPixmap(T.pixmap(name, T.MUTED, 18))
    return lb
