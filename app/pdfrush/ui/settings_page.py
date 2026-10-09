"""Settings: where files go, Office engine, AI brain, extras."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QWidget

from .. import __version__, paths
from ..core import llm
from .widgets import Page, Segmented, button, card, label, open_path, run_bg


def form(grid: QGridLayout, r: int, name: str, w, hint=None):
    lb = label(name, "muted")
    lb.setFixedWidth(150)
    grid.addWidget(lb, r, 0)
    grid.addWidget(w, r, 1, Qt.AlignLeft)
    if hint is not None:
        grid.addWidget(hint, r, 2, Qt.AlignLeft)


class SettingsPage(Page):
    def __init__(self, main=None):
        super().__init__("Settings", "")
        self.main = main
        s = paths.settings

        # ---- output
        c, v = card()
        v.addWidget(label("Saving", "h2"))
        row = QHBoxLayout()
        self.out = QLineEdit(str(paths.out_dir()))
        self.out.setReadOnly(True)
        ch = button("Change", "folder")
        ch.clicked.connect(self._pick_out)
        op = button("Open", "open", "ghost")
        op.clicked.connect(lambda: open_path(paths.out_dir()))
        row.addWidget(self.out, 1)
        row.addWidget(ch)
        row.addWidget(op)
        v.addLayout(row)
        self.next_to = QCheckBox("Save results next to the original file instead")
        self.next_to.setChecked(bool(s.get("save_next_to_input")))
        self.next_to.toggled.connect(lambda on: self._set("save_next_to_input", on))
        v.addWidget(self.next_to)
        self.open_after = QCheckBox("Show the result in its folder when done")
        self.open_after.setChecked(bool(s.get("open_folder_after", True)))
        self.open_after.toggled.connect(lambda on: self._set("open_folder_after", on))
        v.addWidget(self.open_after)
        self.body.addWidget(c)

        # ---- office
        c2, v2 = card()
        v2.addWidget(label("Word, PowerPoint & Excel conversion", "h2"))
        v2.addWidget(label("Office files are converted with Microsoft Office if it's installed (best fidelity), "
                           "otherwise with the free LibreOffice.", "muted", True))
        r2 = QHBoxLayout()
        self.office = QComboBox()
        self.office.addItems(["Auto", "Microsoft Office", "LibreOffice"])
        self.office.setCurrentText(s.get("office_engine", "Auto"))
        self.office.currentTextChanged.connect(lambda t: self._set("office_engine", t))
        r2.addWidget(self.office)
        from ..core.convert import _soffice
        so = _soffice()
        r2.addWidget(label("LibreOffice: " + ("found ✓" if so else "not found"), "faint"))
        if not so:
            get = button("Get LibreOffice (free)", "download", "ghost")
            get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.libreoffice.org/download/")))
            r2.addWidget(get)
        r2.addStretch(1)
        v2.addLayout(r2)
        gs = paths.ghostscript()
        v2.addWidget(label("Ghostscript (optional, for stronger compression, grayscale and true PDF/A): " +
                           ("found ✓" if gs else "not installed - PDFRush uses its built-in engine"), "faint", True))
        self.body.addWidget(c2)

        # ---- AI
        from .. import SUITE
        if SUITE:
            c3, v3 = card()
            v3.addWidget(label("AI brain", "h2"))
            v3.addWidget(label("RushSuite shares one AI setup between PDF tools and Read & Listen. Set your free "
                               "Gemini/Groq key or the offline model in Read & Listen → Settings.", "muted", True))
            gb = button("Open AI settings", "ai")
            gb.clicked.connect(lambda: self.main.suite.show_read("settings") if self.main and self.main.suite else None)
            v3.addWidget(gb, 0, Qt.AlignLeft)
            self.body.addWidget(c3)
        else:
            c3, v3 = card()
            v3.addWidget(label("AI brain", "h2"))
            v3.addWidget(label("Used by AI Summarizer and Translate PDF. Online is fastest (Gemini and Groq have free "
                               "keys); Offline runs a local model with no internet.", "muted", True))
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
            self.getkey = button("Get a free key", "web", "ghost")
            self.getkey.clicked.connect(self._open_key_page)
            self.model = QLineEdit(s.get("ai_model", ""))
            self.model.setMinimumWidth(260)
            self.base = QLineEdit(s.get("ai_base_url", ""))
            self.base.setPlaceholderText("http://localhost:1234/v1 (custom only)")
            self.base.setMinimumWidth(380)
            krow = QHBoxLayout()
            krow.setContentsMargins(0, 0, 0, 0)
            krow.addWidget(self.key)
            krow.addWidget(self.getkey)
            kw = QWidget()
            kw.setLayout(krow)
            form(g, 0, "Mode", self.mode)
            form(g, 1, "Online provider", self.provider)
            form(g, 2, "API key", kw)
            form(g, 3, "Model", self.model, label("leave empty for the default", "faint"))
            form(g, 4, "Custom URL", self.base)
            self.local_lbl = label("", "faint", True)
            lm = button("Choose model file (.gguf)", "folder", "ghost")
            lm.clicked.connect(self._pick_gguf)
            lw = QHBoxLayout()
            lw.setContentsMargins(0, 0, 0, 0)
            lw.addWidget(self.local_lbl, 1)
            lw.addWidget(lm)
            lww = QWidget()
            lww.setLayout(lw)
            form(g, 5, "Offline model", lww)
            g.setColumnStretch(2, 1)
            v3.addLayout(g)
            r = QHBoxLayout()
            sv = button("Save", "check", "primary")
            sv.clicked.connect(self._save_ai)
            test = button("Test AI", "ai")
            test.clicked.connect(self._test)
            r.addWidget(sv)
            r.addWidget(test)
            r.addStretch(1)
            v3.addLayout(r)
            self.test_out = label("", "muted", True)
            v3.addWidget(self.test_out)
            v3.addWidget(label("Keys are stored only on this PC. With an online provider, the text of the PDF you "
                               "summarize/translate is sent to that provider.", "faint", True))
            self.body.addWidget(c3)
            self._prov(self.provider.currentText())

        c4, v4 = card()
        v4.addWidget(label("About", "h2"))
        v4.addWidget(label(f"PDFRush {__version__} - every tool runs on this PC; your files never leave it (except "
                           "text sent to an online AI you chose). Built with pikepdf/qpdf, PDFium, ReportLab, "
                           "pdfplumber, pypdf, RapidOCR and llama.cpp.", "faint", True))
        row4 = QHBoxLayout()
        cfg = button("Open settings folder", "folder", "ghost")
        cfg.clicked.connect(lambda: open_path(paths.config_dir()))
        row4.addWidget(cfg)
        row4.addStretch(1)
        v4.addLayout(row4)
        self.body.addWidget(c4)
        self.finish()
        if not SUITE:
            self._local_info()


    def _set(self, k, v):
        paths.settings[k] = v
        paths.settings.save()

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Save results in", str(paths.out_dir()))
        if d:
            self._set("out_dir", d)
            self.out.setText(d)

    def _prov(self, name):
        _kind, _base, model, url = llm.PROVIDERS.get(name, ("", "", "", ""))
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
        if self.main is not None:
            self.main.toast.show_message("AI settings saved")

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
                               else "Not installed (optional): run build.bat with 'ai' or choose a .gguf file")

    def _pick_gguf(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a GGUF model", str(paths.GGUF_DIR), "GGUF model (*.gguf)")
        if f:
            self._set("local_model", f)
            llm.LOCAL.stop()
            self._local_info()

