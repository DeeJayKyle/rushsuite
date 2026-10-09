"""Compare PDF: side-by-side view with highlighted differences + downloadable report."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import paths
from ..core import compare as C
from ..core.registry import TOOLS, run_tool
from ..core.util import PDFIUM_LOCK
from . import theme as T
from .tool_page import output_dir_for, remember, unlock_inputs
from .widgets import (Busy, IconBadge, Segmented, button, card, error_box, label, open_path, pil_to_pixmap, run_bg)


class Slot(QFrame):
    """Drop target for one of the two PDFs."""

    def __init__(self, title: str, on_change):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.path: Path | None = None
        self.on_change = on_change
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        self.t = label(title, "h2")
        self.t.setAlignment(Qt.AlignCenter)
        self.s = label("Drop a PDF or click Choose", "muted")
        self.s.setAlignment(Qt.AlignCenter)
        b = button("Choose", "plus")
        b.clicked.connect(self._browse)
        v.addWidget(self.t)
        v.addWidget(self.s)
        v.addWidget(b, 0, Qt.AlignCenter)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose PDF", "", "PDF files (*.pdf)")
        if f:
            self.set(Path(f))

    def set(self, p: Path):
        self.path = p
        self.s.setText(p.name)
        self.on_change()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        fs = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if fs:
            self.set(Path(fs[0]))


class ComparePage(QWidget):
    def __init__(self, main=None):
        super().__init__()
        self.main = main
        self.tool = TOOLS["compare"]
        self.diff = None
        self.page = 0
        self.a = self.b = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 14)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(IconBadge(self.tool.icon, self.tool.color, 40))
        hv = QVBoxLayout()
        hv.setSpacing(0)
        hv.addWidget(label(self.tool.name, "h2"))
        hv.addWidget(label(self.tool.desc, "faint"))
        head.addLayout(hv, 1)
        self.mode = Segmented(["Text", "Visual"], "Text", {"Text": "Words added, removed or changed",
                                                            "Visual": "Every pixel that differs (images, layout)"})
        self.mode.changed.connect(lambda _m: self.show_page())
        head.addWidget(self.mode)
        self.case = QCheckBox("Ignore case")
        head.addWidget(self.case)
        self.go = button("Compare", "compare", "primary")
        self.go.clicked.connect(self.run)
        head.addWidget(self.go)
        self.rep = button("Save report", "save")
        self.rep.clicked.connect(self.report)
        head.addWidget(self.rep)
        root.addLayout(head)

        slots = QHBoxLayout()
        self.sa = Slot("Original", self._changed)
        self.sb = Slot("Changed version", self._changed)
        slots.addWidget(self.sa)
        slots.addWidget(self.sb)
        root.addLayout(slots)

        body = QHBoxLayout()
        body.setSpacing(12)
        views = QHBoxLayout()
        self.va, self.vb = QLabel(), QLabel()
        for v in (self.va, self.vb):
            v.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(v)
            sc.setObjectName("canvasbox")
            views.addWidget(sc, 1)
        body.addLayout(views, 1)
        side, sv = card()
        side.setFixedWidth(300)
        nav = QHBoxLayout()
        pb = button("", "left", "ghost")
        nb = button("", "right", "ghost")
        pb.clicked.connect(lambda: self.goto(self.page - 1))
        nb.clicked.connect(lambda: self.goto(self.page + 1))
        self.page_lbl = label("", "muted")
        nav.addWidget(pb)
        nav.addWidget(self.page_lbl, 1, Qt.AlignCenter)
        nav.addWidget(nb)
        sv.addLayout(nav)
        self.summary = label("Add two PDFs and press Compare.", "muted", True)
        sv.addWidget(self.summary)
        self.changes = QListWidget()
        self.changes.itemClicked.connect(lambda it: self.goto(it.data(Qt.UserRole)))
        sv.addWidget(self.changes, 1)
        legend = QHBoxLayout()
        legend.addWidget(label("■ removed", ""))
        legend.addWidget(label("■ added", ""))
        legend.itemAt(0).widget().setStyleSheet(f"color: {T.DANGER};")
        legend.itemAt(1).widget().setStyleSheet(f"color: {T.SUCCESS};")
        sv.addLayout(legend)
        self.busy = Busy()
        sv.addWidget(self.busy)
        body.addWidget(side)
        root.addLayout(body, 1)
        self._changed()

    def set_files(self, files):
        files = [Path(f) for f in files]
        if files:
            self.sa.set(files[0])
        if len(files) > 1:
            self.sb.set(files[1])

    def _changed(self):
        ok = bool(self.sa.path and self.sb.path)
        self.go.setEnabled(ok)
        self.rep.setEnabled(ok and self.diff is not None)

    def run(self):
        fs = unlock_inputs(self, [self.sa.path, self.sb.path])
        if not fs:
            return
        self.a, self.b = fs
        self.go.setEnabled(False)
        self.busy.start("Comparing…")
        run_bg(self, C.text_diff, self.a, self.b, self.case.isChecked(), on_done=self._done, on_fail=self._fail)

    def _fail(self, msg):
        self.busy.done()
        self.go.setEnabled(True)
        error_box(self, msg)

    def _done(self, d):
        self.busy.done()
        self.go.setEnabled(True)
        self.diff = d
        self._changed()
        added = sum(1 for c in d.changes if c.kind == "added")
        removed = sum(1 for c in d.changes if c.kind == "removed")
        changed = sum(1 for c in d.changes if c.kind == "changed")
        self.summary.setText(f"Text similarity {d.similarity * 100:.1f}%\n{changed} changed · {added} added · "
                             f"{removed} removed" if d.changes else "No text differences. Try Visual mode to check "
                                                                    "images and layout.")
        self.changes.clear()
        for c in d.changes[:2000]:
            pg = c.page_b if c.page_b is not None else c.page_a
            if c.kind == "added":
                txt = f"+ {c.new}"
            elif c.kind == "removed":
                txt = f"− {c.old}"
            else:
                txt = f"{c.old}  →  {c.new}"
            it = QListWidgetItem(T.icon({"added": "plus", "removed": "x"}.get(c.kind, "edit"),
                                        {"added": T.SUCCESS, "removed": T.DANGER}.get(c.kind, T.WARN), 16),
                                 f"p{pg + 1}  {txt[:120]}")
            it.setData(Qt.UserRole, pg)
            self.changes.addItem(it)
        self.goto(0)

    def goto(self, i):
        if self.diff is None:
            return
        n = max(self.diff.pages_a, self.diff.pages_b)
        if not (0 <= i < n):
            return
        self.page = i
        self.page_lbl.setText(f"Page {i + 1} / {n}")
        self.show_page()

    def show_page(self):
        if self.diff is None:
            return
        i = self.page
        width = max(300, (self.width() - 380) // 2)
        if not PDFIUM_LOCK.acquire(timeout=0.1):     # busy writing the report - retry shortly
            QTimer.singleShot(400, self.show_page)
            return
        try:
            if self.mode.value() == "Visual" and i < self.diff.pages_a and i < self.diff.pages_b:
                ia, ib, frac = C.visual_diff(self.a, self.b, i, i)
                self.summary.setToolTip(f"{frac * 100:.2f}% of this page differs")
            else:
                ia = C.render_marked(self.a, i, self.diff.marks_a.get(i, []), C.RED) if i < self.diff.pages_a else None
                ib = (C.render_marked(self.b, i, self.diff.marks_b.get(i, []), C.GREEN) if i < self.diff.pages_b
                      else None)
        finally:
            PDFIUM_LOCK.release()
        for view, img in ((self.va, ia), (self.vb, ib)):
            if img is None:
                view.setText("(no page)")
                continue
            pm = pil_to_pixmap(img)
            view.setPixmap(pm.scaledToWidth(min(width, pm.width() * 2), Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.show_page()

    def report(self):
        if not (self.a and self.b):
            return
        out = output_dir_for([self.sa.path])
        self.busy.start("Writing report…")

        def ok(res):
            self.busy.done()
            remember(res)
            if self.main is not None:
                self.main.toast.show_message(f"Report saved: {res[0].name}")
            if paths.settings.get("open_folder_after"):
                open_path(res[0], select=True)
        run_bg(self, run_tool, "compare", [self.a, self.b], out,
               {"mode": self.mode.value(), "ignore_case": self.case.isChecked()},
               on_progress=self.busy.update_, on_done=ok, on_fail=self._fail)
