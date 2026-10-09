"""Organize PDF: visual page sorter - drag to reorder, rotate, delete, duplicate, insert blank pages or other PDFs."""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import paths
from ..core.organize import build_from_refs
from ..core.registry import TOOLS
from ..core.util import Busy as PdfBusy, out_name, pdfium_lock
from . import theme as T
from .tool_page import output_dir_for, remember, unlock_inputs
from .widgets import Busy, DropZone, IconBadge, button, collect_files, error_box, label, open_path, pil_to_pixmap, run_bg

ROLE = Qt.UserRole


class PageGrid(QListWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("thumbs")
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(130, 170))
        self.setGridSize(QSize(170, 222))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSpacing(8)
        self.setAcceptDrops(True)
        self.on_files = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            if self.on_files:
                self.on_files([u.toLocalFile() for u in e.mimeData().urls()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class OrganizePage(QWidget):
    def __init__(self, main=None):
        super().__init__()
        self.main = main
        self.tool = TOOLS["organize"]
        self.first: Path | None = None
        self._pix: dict = {}
        self._queue: list = []
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 14)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(IconBadge(self.tool.icon, self.tool.color, 40))
        hv = QVBoxLayout()
        hv.setSpacing(0)
        hv.addWidget(label(self.tool.name, "h2"))
        self.info = label(self.tool.desc, "faint")
        hv.addWidget(self.info)
        head.addLayout(hv, 1)
        self.save_b = button("Save PDF", "save", "primary")
        self.save_b.clicked.connect(self.save)
        head.addWidget(self.save_b)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        acts = [("Add PDF", "plus", self.add_pdf), ("Blank page", "blank", self.add_blank),
                ("Rotate left", "rotl", lambda: self.rotate(-90)), ("Rotate right", "rotate", lambda: self.rotate(90)),
                ("Duplicate", "layers", self.duplicate), ("Delete", "trash", self.delete),
                ("Reverse", "split", self.reverse), ("Select all", "check", lambda: self.grid.selectAll())]
        self.bar_buttons = []
        for text, icon, fn in acts:
            b = button(text, icon, "ghost")
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.bar_buttons.append(b)
        bar.addStretch(1)
        self.count = label("", "muted")
        bar.addWidget(self.count)
        root.addLayout(bar)

        self.stack = QStackedWidget()
        self.drop = DropZone("Open a PDF to organize", "Drop one or more PDFs here (they'll be combined)", "upload",
                             folders=False, height=320)
        self.drop.dropped.connect(self._files)
        dz = QWidget()
        dl = QVBoxLayout(dz)
        dl.addStretch(1)
        dl.addWidget(self.drop)
        dl.addStretch(2)
        self.stack.addWidget(dz)
        self.grid = PageGrid()
        self.grid.on_files = self._files
        self.grid.model().rowsMoved.connect(lambda *_: self._renumber())
        self.stack.addWidget(self.grid)
        root.addWidget(self.stack, 1)
        root.addWidget(label("Tip: drag pages to reorder. Select several with Ctrl/Shift. Drop more PDFs onto the "
                             "grid to add their pages.", "faint"))
        self.busy = Busy()
        root.addWidget(self.busy)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._render_some)
        self._refresh()

    # ------------------------------------------------------------------ loading
    def set_files(self, files):
        self.grid.clear()
        self.first = None
        self._files([str(f) for f in files])

    def _files(self, items):
        fs = collect_files(items, [".pdf"])
        fs = unlock_inputs(self, fs) or []
        for f in fs:
            try:
                with pdfium_lock():
                    doc = pdfium.PdfDocument(str(f))
                    n = len(doc)
                    doc.close()
            except Exception as e:  # noqa: BLE001
                error_box(self, f"Couldn't open {f.name}: {e}")
                continue
            if self.first is None:
                self.first = f
            tag = f.stem[:14]
            for i in range(n):
                it = QListWidgetItem(T.icon("pdf", T.FAINT, 48), "")
                it.setData(ROLE, {"src": str(f), "page": i, "rot": 0, "tag": tag})
                self.grid.addItem(it)
                self._queue.append(it)
        self.timer.start(10)
        self._renumber()

    def _render_some(self):
        for _ in range(3):
            if not self._queue:
                self.timer.stop()
                return
            it = self._queue[0]
            try:
                self._set_icon(it)
            except PdfBusy:               # PDFium busy with a background job - retry on next tick
                return
            except RuntimeError:          # item was deleted meanwhile
                pass
            self._queue.pop(0)

    def _base_pixmap(self, src: str, page: int):
        key = (src, page)
        if key not in self._pix:
            with pdfium_lock(0.05):
                doc = pdfium.PdfDocument(src)
                pg = doc[page]
                w, h = pg.get_size()
                img = pg.render(scale=260 / max(w, h)).to_pil()
                pg.close()
                doc.close()
            self._pix[key] = pil_to_pixmap(img)
        return self._pix[key]

    def _set_icon(self, it: QListWidgetItem):
        d = it.data(ROLE)
        if d["src"] is None:
            from PySide6.QtGui import QPixmap
            pm = QPixmap(130, 184)
            pm.fill(Qt.white)
        else:
            pm = self._base_pixmap(d["src"], d["page"])
        if d["rot"]:
            pm = pm.transformed(QTransform().rotate(d["rot"]), Qt.SmoothTransformation)
        it.setIcon(QIcon(pm))

    def _renumber(self):
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            d = it.data(ROLE)
            label_ = f"{i + 1}" + (f"  ·  {d['tag']} p{d['page'] + 1}" if d["src"] else "  ·  blank")
            it.setText(label_)
        self._refresh()

    def _refresh(self):
        n = self.grid.count()
        self.stack.setCurrentIndex(1 if n else 0)
        self.count.setText(f"{n} page{'s' if n != 1 else ''}" if n else "")
        self.save_b.setEnabled(n > 0)
        for b in self.bar_buttons[1:]:
            b.setEnabled(n > 0)

    # ------------------------------------------------------------------ actions
    def _selected(self) -> list[QListWidgetItem]:
        return self.grid.selectedItems()

    def add_pdf(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Add PDF", "", "PDF files (*.pdf)")
        if fs:
            self._files(fs)

    def add_blank(self):
        sel = self._selected()
        row = (max(self.grid.row(i) for i in sel) + 1) if sel else self.grid.count()
        size = (595.28, 841.89)
        ref = sel[0].data(ROLE) if sel else (self.grid.item(0).data(ROLE) if self.grid.count() else None)
        if ref and ref["src"]:
            try:
                with pdfium_lock(0.5):
                    doc = pdfium.PdfDocument(ref["src"])
                    size = tuple(doc[ref["page"]].get_size())
                    doc.close()
            except Exception:
                pass
        it = QListWidgetItem("")
        it.setData(ROLE, {"src": None, "page": 0, "rot": 0, "tag": "", "size": size})
        self.grid.insertItem(row, it)
        self._set_icon(it)
        self._renumber()

    def _icon_later(self, it):
        try:
            self._set_icon(it)
        except PdfBusy:
            self._queue.append(it)
            self.timer.start(10)

    def rotate(self, deg: int):
        for it in self._selected() or [self.grid.item(i) for i in range(self.grid.count())]:
            d = dict(it.data(ROLE))
            d["rot"] = (d["rot"] + deg) % 360
            it.setData(ROLE, d)
            self._icon_later(it)

    def duplicate(self):
        for it in sorted(self._selected(), key=self.grid.row, reverse=True):
            new = QListWidgetItem("")
            new.setData(ROLE, dict(it.data(ROLE)))
            self.grid.insertItem(self.grid.row(it) + 1, new)
            self._icon_later(new)
        self._renumber()

    def delete(self):
        sel = self._selected()
        if not sel:
            error_box(self, "Select the pages to delete first.")
            return
        for it in sel:
            if it in self._queue:
                self._queue.remove(it)
            self.grid.takeItem(self.grid.row(it))
        self._renumber()

    def reverse(self):
        items = [self.grid.takeItem(0) for _ in range(self.grid.count())]
        for it in reversed(items):
            self.grid.addItem(it)
        self._renumber()

    def save(self):
        refs = []
        for i in range(self.grid.count()):
            d = self.grid.item(i).data(ROLE)
            refs.append((d["src"], d["page"], d["rot"], d.get("size")))
        if not refs:
            return
        first = self.first or Path(paths.out_dir()) / "organized.pdf"
        dest = out_name(first, output_dir_for([first]), "organized")
        self.save_b.setEnabled(False)
        self.busy.start("Saving…")

        def ok(res):
            self.busy.done()
            self.save_b.setEnabled(True)
            remember([Path(res)])
            if self.main is not None:
                self.main.toast.show_message(f"Saved {Path(res).name}")
            if paths.settings.get("open_folder_after"):
                open_path(res, select=True)

        def fail(msg):
            self.busy.done()
            self.save_b.setEnabled(True)
            error_box(self, msg)
        run_bg(self, build_from_refs, refs, dest, on_done=ok, on_fail=fail)
