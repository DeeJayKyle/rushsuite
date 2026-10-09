"""Generic tool screen, built automatically from a tool's declaration (files in -> options -> run -> results)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit,
                               QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

from .. import paths
from ..core.registry import TOOLS, Tool, run_tool
from . import theme as T
from .widgets import (Busy, DropZone, IconBadge, Page, ParamForm, button, card, collect_files, error_box, ext_filter,
                      file_thumb, human_size, label, open_path, run_bg)

VERBS = {"merge": "Merge PDF", "split": "Split PDF", "compress": "Compress PDF", "protect": "Protect PDF",
         "unlock": "Unlock PDF", "rotate": "Rotate PDF", "repair": "Repair PDF", "ocr_pdf": "Run OCR",
         "ai_summarizer": "Summarize", "translate_pdf": "Translate", "redact": "Redact", "watermark": "Add watermark",
         "page_numbers": "Add page numbers", "flatten": "Flatten", "pdfa": "Convert to PDF/A",
         "remove_pages": "Remove pages", "extract_pages": "Extract pages", "crop": "Crop PDF",
         "scan_to_pdf": "Create PDF"}


def output_dir_for(files: list[Path]) -> Path:
    if paths.settings.get("save_next_to_input") and files and files[0].parent.exists():
        return files[0].parent
    return paths.out_dir()


def remember(outputs: list[Path]) -> None:
    rec = [str(p) for p in outputs] + [r for r in paths.settings.get("recent", []) if r not in map(str, outputs)]
    paths.settings["recent"] = rec[:60]
    paths.settings.save()


def unlock_inputs(parent, files: list[Path]) -> list[Path] | None:
    """Ask for passwords of encrypted PDFs; returns decrypted temporary copies (None = cancelled)."""
    import pikepdf
    out = []
    for f in files:
        if f.suffix.lower() != ".pdf":
            out.append(f)
            continue
        try:
            pikepdf.open(str(f)).close()
            out.append(f)
            continue
        except pikepdf.PasswordError:
            pass
        except Exception:
            out.append(f)          # damaged etc. - let the tool report it
            continue
        while True:
            pw, ok = QInputDialog.getText(parent, "Password needed", f"'{f.name}' is protected.\nEnter its password:",
                                          QLineEdit.Password)
            if not ok:
                return None
            try:
                pdf = pikepdf.open(str(f), password=pw)
            except pikepdf.PasswordError:
                continue
            tmp = Path(tempfile.mkdtemp(prefix="pdfrush_")) / f.name
            pdf.save(str(tmp))
            pdf.close()
            out.append(tmp)
            break
    return out


class FileList(QListWidget):
    """Thumbnails of the chosen files; drag to reorder."""
    changed = Signal()

    def __init__(self, accepts: list[str]):
        super().__init__()
        self.accepts = accepts
        self.setObjectName("thumbs")
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(110, 140))
        self.setGridSize(QSize(150, 200))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWordWrap(True)
        self.setMinimumHeight(220)
        self.setSpacing(6)
        self.model().rowsMoved.connect(lambda *_: self.changed.emit())

    def add(self, files: list[Path]):
        have = set(self.files())
        for f in files:
            if f in have:
                continue
            it = QListWidgetItem(f"{f.name}\n{human_size(f.stat().st_size)}")
            pm = file_thumb(f, 110)
            it.setIcon(T.icon("pdf", T.ACCENT, 64) if pm is None else QIcon(pm))
            it.setData(Qt.UserRole, str(f))
            it.setToolTip(str(f))
            self.addItem(it)
        self.changed.emit()

    def files(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.UserRole)) for i in range(self.count())]

    def remove_selected(self):
        for it in self.selectedItems():
            self.takeItem(self.row(it))
        self.changed.emit()

    def sort_by_name(self):
        fs = sorted(self.files(), key=lambda p: p.name.lower())
        self.clear()
        self.add(fs)

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
            self.add(collect_files([u.toLocalFile() for u in e.mimeData().urls()], self.accepts))
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class ResultsCard(QWidget):
    """Output files with open / show buttons and 'continue with another tool'."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.box, self.v = card()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)
        self.hide()

    def show_results(self, outputs: list[Path], note: str = ""):
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                _clear_layout(it.layout())
        head = QHBoxLayout()
        head.addWidget(IconBadge("check", T.SUCCESS, 34))
        txt = QVBoxLayout()
        txt.setSpacing(2)
        txt.addWidget(label("Done!" if len(outputs) == 1 else f"Done - {len(outputs)} files", "h2"))
        if note:
            txt.addWidget(label(note, "muted", True))
        head.addLayout(txt, 1)
        folder = outputs[0].parent if outputs else paths.out_dir()
        b = button("Open folder", "folder")
        b.clicked.connect(lambda: open_path(outputs[0] if outputs else folder, select=True))
        head.addWidget(b)
        self.v.addLayout(head)
        for f in outputs[:30]:
            row = QHBoxLayout()
            row.addWidget(IconBadge("pdf" if f.suffix.lower() == ".pdf" else "note", T.ACCENT2, 30))
            name = label(f"{f.name}", "")
            name.setToolTip(str(f))
            row.addWidget(name, 1)
            try:
                row.addWidget(label(human_size(f.stat().st_size), "faint"))
            except OSError:
                pass
            ob = button("Open", "open", "ghost")
            ob.clicked.connect(lambda _=False, f=f: _open_file(f))
            row.addWidget(ob)
            self.v.addLayout(row)
        if len(outputs) > 30:
            self.v.addWidget(label(f"…and {len(outputs) - 30} more in {folder}", "faint"))
        pdfs = [f for f in outputs if f.suffix.lower() == ".pdf"]
        suite = getattr(self.main, "suite", None)
        readable = [f for f in outputs if f.suffix.lower() in (".pdf", ".txt", ".md", ".docx", ".epub", ".html")]
        if suite is not None and readable:
            lb = button("Listen to " + ("it" if len(readable) == 1 else f"these {len(readable)} files"), "volume")
            lb.clicked.connect(lambda: suite.listen(readable))
            self.v.addWidget(lb, 0, Qt.AlignLeft)
        if pdfs and self.main is not None:
            row = QHBoxLayout()
            row.addWidget(label("Continue with", "muted"))
            combo = QComboBox()
            options = [t for t in TOOLS.values() if ".pdf" in t.accepts]
            for t in options:
                combo.addItem(T.icon(t.icon, t.color, 16), t.name, t.id)
            row.addWidget(combo, 1)
            go = button("Go", "right")
            go.clicked.connect(lambda: self.main.open_tool(combo.currentData(), pdfs))
            row.addWidget(go)
            self.v.addLayout(row)
        self.show()


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear_layout(it.layout())


def _open_file(f: Path):
    import os
    import sys
    if sys.platform == "win32":
        os.startfile(str(f))  # type: ignore[attr-defined]


class ToolPage(Page):
    def __init__(self, tool: Tool, main=None):
        super().__init__("", "", max_width=1100)
        self.tool, self.main = tool, main
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(IconBadge(tool.icon, tool.color, 54))
        tv = QVBoxLayout()
        tv.setSpacing(3)
        tv.addWidget(label(tool.name, "h1"))
        tv.addWidget(label(tool.desc, "muted", True))
        head.addLayout(tv, 1)
        self.body.addLayout(head)

        exts = tool.accepts
        many = tool.combine or tool.max_files != 1
        hint = "Drop files or a folder here" if many else "Drop a file here"
        if tool.url_input:
            hint += " - or paste a web address below"
        self.drop = DropZone(f"Select {', '.join(e.strip('.').upper() for e in exts[:4])} file"
                             f"{'s' if many else ''}", hint, "upload", folders=many,
                             filter_=ext_filter(exts), height=160)
        self.drop.dropped.connect(self._dropped)
        self.body.addWidget(self.drop)

        self.files_box, fv = card()
        top = QHBoxLayout()
        self.count_lbl = label("", "h2")
        top.addWidget(self.count_lbl)
        top.addStretch(1)
        if tool.combine:
            top.addWidget(label("Drag to change the order", "faint"))
            az = button("A-Z", "", "ghost", "Sort by name")
            az.clicked.connect(lambda: self.list.sort_by_name())
            top.addWidget(az)
        add = button("Add more", "plus")
        add.clicked.connect(self.drop._browse_files)
        rm = button("Remove", "trash", "ghost", "Remove selected files")
        rm.clicked.connect(lambda: self.list.remove_selected())
        clr = button("Clear", "x", "ghost")
        clr.clicked.connect(lambda: (self.list.clear(), self._refresh()))
        for w in (add, rm, clr):
            top.addWidget(w)
        fv.addLayout(top)
        self.list = FileList(exts)
        self.list.changed.connect(self._refresh)
        fv.addWidget(self.list)
        self.body.addWidget(self.files_box)

        self.form = None
        visible = [p for p in tool.params if not p.key.startswith("_")]
        if visible:
            opt, ov = card()
            ov.addWidget(label("Options", "h2"))
            self.form = ParamForm(tool.params)
            ov.addWidget(self.form)
            self.body.addWidget(opt)
        self.extra_card()

        run_row = QHBoxLayout()
        self.dest_lbl = label("", "faint")
        run_row.addWidget(self.dest_lbl, 1)
        ch = button("Change", "folder", "ghost", "Choose where results are saved")
        ch.clicked.connect(self._choose_out)
        run_row.addWidget(ch)
        self.run_btn = button(VERBS.get(tool.id, tool.name), tool.icon, "primary")
        self.run_btn.setMinimumWidth(200)
        self.run_btn.clicked.connect(self.run)
        run_row.addWidget(self.run_btn)
        self.body.addLayout(run_row)
        self.busy = Busy()
        self.body.addWidget(self.busy)
        self.results = ResultsCard(main)
        self.body.addWidget(self.results)
        self.finish()
        self._refresh()

    # hooks for subclasses
    def extra_card(self):
        pass

    def extra_params(self) -> dict:
        return {}

    def set_files(self, files: list[Path]):
        self.list.clear()
        self.list.add([Path(f) for f in files])

    def _dropped(self, items):
        fs = collect_files(items, self.tool.accepts)
        if not fs and items:
            error_box(self, f"{self.tool.name} works with: {', '.join(self.tool.accepts)}")
            return
        if self.tool.max_files == 1 or (not self.tool.combine and self.tool.max_files and
                                        len(fs) + self.list.count() > self.tool.max_files):
            self.list.clear()
            fs = fs[: max(1, self.tool.max_files)]
        self.list.add(fs)

    def _refresh(self):
        n = self.list.count()
        self.files_box.setVisible(n > 0)
        self.count_lbl.setText(f"{n} file{'s' if n != 1 else ''}")
        self.dest_lbl.setText(f"Saves to: {output_dir_for(self.list.files())}")
        need = max(1, self.tool.min_files)
        self.run_btn.setEnabled(n >= need or (self.tool.url_input and n == 0))

    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, "Save results in", str(paths.out_dir()))
        if d:
            paths.settings["out_dir"] = d
            paths.settings["save_next_to_input"] = False
            paths.settings.save()
            self._refresh()

    def params(self) -> dict:
        p = self.form.values() if self.form else {}
        p.update(self.extra_params())
        return p

    def run(self):
        files = self.list.files()
        if len(files) < self.tool.min_files and not self.tool.url_input:
            error_box(self, f"Add at least {self.tool.min_files} files.")
            return
        if self.tool.id != "unlock":
            files = unlock_inputs(self, files)
            if files is None:
                return
        out = output_dir_for(self.list.files())
        self.run_btn.setEnabled(False)
        self.results.hide()
        self.busy.start(f"{self.tool.name}…")
        before = {f: f.stat().st_size for f in files if f.exists()}
        run_bg(self, run_tool, self.tool.id, files, out, self.params(),
               on_progress=self.busy.update_, on_done=lambda r: self._done(r, before), on_fail=self._fail)

    def _done(self, outputs, before):
        self.busy.done()
        self.run_btn.setEnabled(True)
        outputs = [Path(o) for o in outputs]
        note = ""
        if self.tool.id == "compress" and before and outputs:
            a = sum(before.values())
            b = sum(o.stat().st_size for o in outputs if o.exists())
            if a:
                note = f"{human_size(a)} → {human_size(b)}  ({max(0.0, 100 * (1 - b / a)):.0f}% smaller)"
        remember(outputs)
        self.results.show_results(outputs, note)
        if self.main is not None:
            self.main.toast.show_message(f"{self.tool.name}: done")
        if paths.settings.get("open_folder_after") and outputs:
            open_path(outputs[0], select=True)

    def _fail(self, msg):
        self.busy.done()
        self.run_btn.setEnabled(True)
        error_box(self, msg)

