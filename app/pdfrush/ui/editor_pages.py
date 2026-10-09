"""Interactive screens: Edit PDF, Sign PDF, Redact PDF, Crop PDF and PDF Forms."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import paths
from ..core import edit as E
from ..core import security as S
from ..core.registry import TOOLS
from ..core.util import out_name, parse_pages, pdfium_lock, save
from . import theme as T
from .pdfcanvas import PageCanvas, PdfDoc
from .tool_page import output_dir_for, remember, unlock_inputs
from .widgets import (Busy, DropZone, IconBadge, button, error_box, label, open_path, run_bg, sep)


# ===================================================================== base
class EditorBase(QWidget):
    tool_id = ""
    save_text = "Save"

    def __init__(self, main=None):
        super().__init__()
        self.main = main
        self.tool = TOOLS[self.tool_id]
        self.doc: PdfDoc | None = None
        self.src: Path | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 14)
        root.setSpacing(12)

        # header
        head = QHBoxLayout()
        head.addWidget(IconBadge(self.tool.icon, self.tool.color, 40))
        hv = QVBoxLayout()
        hv.setSpacing(0)
        hv.addWidget(label(self.tool.name, "h2"))
        self.file_lbl = label(self.tool.desc, "faint")
        hv.addWidget(self.file_lbl)
        head.addLayout(hv, 1)
        self.nav = QHBoxLayout()
        self.prev_b = button("", "left", "ghost", "Previous page")
        self.next_b = button("", "right", "ghost", "Next page")
        self.page_lbl = label("", "muted")
        zo = button("", "zoomout", "ghost", "Zoom out")
        zi = button("", "zoomin", "ghost", "Zoom in")
        fit = button("Fit", "", "ghost", "Fit page width")
        self.prev_b.clicked.connect(lambda: self.goto(self.canvas.page - 1))
        self.next_b.clicked.connect(lambda: self.goto(self.canvas.page + 1))
        zo.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom / 1.2))
        zi.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom * 1.2))
        fit.clicked.connect(lambda: self.canvas.fit_width(self.scroll.viewport().width()))
        for w in (self.prev_b, self.page_lbl, self.next_b, zo, zi, fit):
            self.nav.addWidget(w)
        head.addLayout(self.nav)
        openb = button("Open PDF", "folder")
        openb.clicked.connect(self._browse)
        head.addWidget(openb)
        self.save_b = button(self.save_text, "save", "primary")
        self.save_b.clicked.connect(self.save)
        head.addWidget(self.save_b)
        root.addLayout(head)

        # body: stack (drop zone | editor)
        self.stack = QStackedWidget()
        self.drop = DropZone(f"Open a PDF to {self.tool.name.split()[0].lower()}", "Drop a PDF here", "upload",
                             folders=False, height=320)
        self.drop.dropped.connect(lambda fs: fs and self.load(Path(fs[0])))
        dz = QWidget()
        dl = QVBoxLayout(dz)
        dl.addStretch(1)
        dl.addWidget(self.drop)
        dl.addStretch(2)
        self.stack.addWidget(dz)

        ed = QWidget()
        el = QHBoxLayout(ed)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(12)
        self.thumbs = QListWidget()
        self.thumbs.setObjectName("thumbs")
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(96, 124))
        self.thumbs.setFixedWidth(140)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.currentRowChanged.connect(self.goto)
        el.addWidget(self.thumbs)
        box = QFrame()
        box.setObjectName("canvasbox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.canvas = PageCanvas()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        bl.addWidget(self.scroll)
        el.addWidget(box, 1)
        panel = QFrame()
        panel.setObjectName("card")
        panel.setFixedWidth(300)
        self.panel = QVBoxLayout(panel)
        self.panel.setContentsMargins(16, 16, 16, 16)
        self.panel.setSpacing(10)
        self.build_panel()
        self.panel.addStretch(1)
        self.busy = Busy()
        self.panel.addWidget(self.busy)
        el.addWidget(panel)
        self.stack.addWidget(ed)
        root.addWidget(self.stack, 1)
        self._show_nav(False)
        self._thumb_i = 0
        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._next_thumbs)

    # ------------------------------------------------------------------ subclasses override
    def build_panel(self):
        pass

    def after_load(self):
        pass

    def save(self):
        pass

    # ------------------------------------------------------------------ doc handling
    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if f:
            self.load(Path(f))

    def set_files(self, files):
        if files:
            self.load(Path(files[0]))

    def load(self, path: Path):
        if path.suffix.lower() != ".pdf":
            error_box(self, "Please choose a PDF file.")
            return
        unlocked = unlock_inputs(self, [path])
        if not unlocked:
            return
        try:
            doc = PdfDoc(unlocked[0])
        except Exception as e:  # noqa: BLE001
            error_box(self, f"Couldn't open {path.name}: {e}")
            return
        if self.doc:
            self.doc.close()
        self.doc, self.src = doc, path
        self.work = unlocked[0]
        self.canvas.items = []
        self.canvas.set_doc(doc)
        self.file_lbl.setText(f"{path.name}  ·  {doc.n} page{'s' if doc.n != 1 else ''}")
        self.thumbs.clear()
        for i in range(doc.n):
            it = QListWidgetItem(str(i + 1))
            self.thumbs.addItem(it)
        self._thumb_i = 0
        self._thumb_timer.start(15)
        self.stack.setCurrentIndex(1)
        self._show_nav(True)
        QTimer.singleShot(50, lambda: self.canvas.fit_width(min(self.scroll.viewport().width(), 1000)))
        self.goto(0)
        self.after_load()

    def _next_thumbs(self):
        if not self.doc or self._thumb_i >= self.doc.n:
            self._thumb_timer.stop()
            return
        for _ in range(4):
            if self._thumb_i >= self.doc.n:
                break
            pm = self.doc.thumb(self._thumb_i, 96)
            if self.doc.busy:                 # PDFium busy with a background job - try again shortly
                return
            item = self.thumbs.item(self._thumb_i)
            if item is not None:
                item.setIcon(QIcon(pm))
            self._thumb_i += 1

    def _show_nav(self, on: bool):
        for i in range(self.nav.count()):
            w = self.nav.itemAt(i).widget()
            if w is not None:
                w.setVisible(on)
        self.save_b.setEnabled(on)

    def goto(self, i: int):
        if not self.doc or not (0 <= i < self.doc.n):
            return
        self.canvas.set_page(i)
        self.page_lbl.setText(f"{i + 1} / {self.doc.n}")
        if self.thumbs.currentRow() != i:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(i)
            self.thumbs.blockSignals(False)
        self.scroll.verticalScrollBar().setValue(0)

    def out_path(self, suffix: str) -> Path:
        return out_name(self.src, output_dir_for([self.src]), suffix)

    def run_save(self, fn, *args, done_msg="Saved"):
        self.save_b.setEnabled(False)
        self.busy.start("Saving…")

        def ok(res):
            self.busy.done()
            self.save_b.setEnabled(True)
            res = Path(res)
            remember([res])
            if self.main is not None:
                self.main.toast.show_message(f"{done_msg}: {res.name}")
            if paths.settings.get("open_folder_after"):
                open_path(res, select=True)

        def fail(msg):
            self.busy.done()
            self.save_b.setEnabled(True)
            error_box(self, msg)
        run_bg(self, fn, *args, on_done=ok, on_fail=fail)

    # ------------------------------------------------------------------ helpers for panels
    def tool_buttons(self, specs: list[tuple[str, str, str]], on_pick) -> QButtonGroup:
        grp = QButtonGroup(self)
        grid = QVBoxLayout()
        grid.setSpacing(4)
        for key, text, icon in specs:
            b = QPushButton(f"  {text}")
            b.setObjectName("toolbtn")
            b.setIcon(T.icon(icon, T.TEXT, 18))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("key", key)
            grp.addButton(b)
            grid.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: on_pick(k))
        grp.buttons()[0].setChecked(True)
        self.panel.addLayout(grid)
        return grp


class ColorButton(QPushButton):
    def __init__(self, color: str = "#D62828"):
        super().__init__()
        self.set(color)
        self.clicked.connect(self._pick)

    def set(self, c: str):
        self.color = c
        self.setText(c.upper())
        self.setStyleSheet(f"QPushButton {{ border-left: 18px solid {c}; text-align: left; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Colour")
        if c.isValid():
            self.set(c.name())


# ===================================================================== Edit PDF
class EditPage(EditorBase):
    tool_id = "edit"
    save_text = "Save PDF"
    TOOLS_ = [("select", "Select / move", "cursor"), ("text", "Add text", "text"), ("image", "Add image", "image"),
              ("rect", "Rectangle", "rect"), ("ellipse", "Ellipse", "ellipse"), ("line", "Line", "line"),
              ("ink", "Draw", "pen"), ("highlight", "Highlight", "highlight"), ("whiteout", "Whiteout (cover)",
                                                                                   "eraser")]

    def build_panel(self):
        self.panel.addWidget(label("Tools", "h2"))
        self.current = "select"
        self.grp = self.tool_buttons(self.TOOLS_, self.pick)
        self.panel.addWidget(sep())
        self.panel.addWidget(label("Style", "h2"))
        row = QHBoxLayout()
        row.addWidget(label("Colour", "muted"))
        self.color = ColorButton("#D62828")
        row.addWidget(self.color, 1)
        self.panel.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(label("Size", "muted"))
        self.size = QSpinBox()
        self.size.setRange(1, 200)
        self.size.setValue(14)
        row2.addWidget(self.size, 1)
        self.bold = QCheckBox("Bold")
        row2.addWidget(self.bold)
        self.panel.addLayout(row2)
        self.fill = QCheckBox("Fill shapes")
        self.panel.addWidget(self.fill)
        apply_b = button("Apply style to selected", "check", "ghost")
        apply_b.clicked.connect(self.restyle)
        self.panel.addWidget(apply_b)
        dele = button("Delete selected", "trash", "ghost")
        dele.clicked.connect(lambda: self.canvas.remove_item(self.canvas.selected))
        self.panel.addWidget(dele)
        self.panel.addWidget(label("Tip: double-click text to change it. Drag the orange corner to resize. "
                                   "Arrow keys nudge, Delete removes.", "faint", True))
        c = self.canvas
        c.clicked.connect(self.on_click)
        c.rect_drawn.connect(self.on_rect)
        c.line_drawn.connect(lambda x1, y1, x2, y2: c.add_item(
            {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": self.color.color,
             "width": max(1, self.size.value() // 5)}))
        c.ink_drawn.connect(lambda pts: c.add_item({"type": "ink", "points": [pts], "color": self.color.color,
                                                    "width": max(1, self.size.value() // 5)}, select=False))
        c.edit_requested.connect(self.edit_text)
        c.selection_changed.connect(self.on_select)

    def pick(self, key):
        self.current = key
        self.canvas.set_mode({"select": "select", "text": "place", "image": "place", "line": "line",
                              "ink": "ink"}.get(key, "rect"))
        if key == "highlight":
            self.color.set("#FFE14D")
        self.canvas.draw_color = QColor(self.color.color)

    def on_click(self, x, y):
        if self.current == "text":
            text, ok = QInputDialog.getMultiLineText(self, "Add text", "Text:")
            if ok and text.strip():
                self.canvas.add_item({"type": "text", "x": x, "y": y, "text": text, "size": self.size.value(),
                                      "color": self.color.color, "bold": self.bold.isChecked()})
                self.back_to_select()
        elif self.current == "image":
            f, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
            if f:
                pm = QPixmap(f)
                w = 160.0
                h = w * pm.height() / max(1, pm.width())
                self.canvas.add_item({"type": "image", "path": f, "x": x, "y": y, "w": w, "h": h, "keep_ratio": True})
                self.back_to_select()
        elif self.current in ("rect", "ellipse", "highlight", "whiteout"):
            self.on_rect(x - 40, y - 15, 80, 30)

    def on_rect(self, x, y, w, h):
        k = self.current
        it = {"type": k, "x": x, "y": y, "w": w, "h": h, "color": self.color.color}
        if k in ("rect", "ellipse"):
            it["width"] = max(1, self.size.value() // 5)
            if self.fill.isChecked():
                it["fill"] = self.color.color
                it["opacity"] = 0.6
        if k == "highlight":
            it["opacity"] = 0.4
        self.canvas.add_item(it)

    def back_to_select(self):
        self.grp.buttons()[0].setChecked(True)
        self.pick("select")

    def edit_text(self, it):
        if it.get("type") != "text":
            return
        text, ok = QInputDialog.getMultiLineText(self, "Edit text", "Text:", it.get("text", ""))
        if ok:
            it["text"] = text
            self.canvas.update()

    def on_select(self, it):
        if it is None:
            return
        if "color" in it:
            self.color.set(it["color"])
        if it.get("type") == "text":
            self.size.setValue(int(it.get("size", 14)))
            self.bold.setChecked(bool(it.get("bold")))

    def restyle(self):
        it = self.canvas.selected
        if it is None:
            return
        it["color"] = self.color.color
        if it.get("type") == "text":
            it["size"] = self.size.value()
            it["bold"] = self.bold.isChecked()
        elif it.get("type") in ("rect", "ellipse", "line", "ink"):
            it["width"] = max(1, self.size.value() // 5)
        self.canvas.update()

    def save(self):
        ops = self.canvas.ops()
        if not ops:
            error_box(self, "Add something to the page first (text, image, shapes…).")
            return
        self.run_save(E.apply_edits, self.work, self.out_path("edited"), ops, done_msg="Saved")


# ===================================================================== Sign PDF
class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 170)
        self.strokes: list[list[QPointF]] = []
        self.color = QColor("#0B2A8C")
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.strokes = []
        self.update()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes:
            self.strokes[-1].append(e.position())
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#DDDDDD"), 1, Qt.DashLine))
        p.drawLine(20, self.height() - 40, self.width() - 20, self.height() - 40)
        self._draw(p, 1.0)
        p.end()

    def _draw(self, p, s, ox=0.0, oy=0.0):
        p.setPen(QPen(self.color, 2.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for st in self.strokes:
            if len(st) == 1:
                p.drawPoint(QPointF((st[0].x() - ox) * s, (st[0].y() - oy) * s))
                continue
            path = QPainterPath(QPointF((st[0].x() - ox) * s, (st[0].y() - oy) * s))
            for pt in st[1:]:
                path.lineTo(QPointF((pt.x() - ox) * s, (pt.y() - oy) * s))
            p.drawPath(path)

    def to_png(self, dest: Path) -> Path | None:
        pts = [pt for st in self.strokes for pt in st]
        if not pts:
            return None
        x0, y0 = min(p.x() for p in pts) - 6, min(p.y() for p in pts) - 6
        x1, y1 = max(p.x() for p in pts) + 6, max(p.y() for p in pts) + 6
        s = 4.0
        pm = QPixmap(int((x1 - x0) * s), int((y1 - y0) * s))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        self._draw(p, s, x0, y0)
        p.end()
        pm.save(str(dest), "PNG")
        return dest


SCRIPT_FONTS = ["Segoe Script", "Lucida Handwriting", "Ink Free", "Brush Script MT", "Segoe Print", "Freestyle Script",
                "Mistral", "Gabriola"]


class SignatureDialog(QDialog):
    """Create a signature or initials: draw, type or upload."""

    def __init__(self, parent, kind: str = "signature"):
        super().__init__(parent)
        self.setWindowTitle("Create your " + kind)
        self.setMinimumWidth(560)
        self.result_path: Path | None = None
        self.kind = kind
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        self.tabs = QTabWidget()
        # draw
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.pad = SignaturePad()
        dl.addWidget(self.pad)
        clr = button("Clear", "x", "ghost")
        clr.clicked.connect(self.pad.clear)
        dl.addWidget(clr, 0, Qt.AlignRight)
        self.tabs.addTab(dw, "Draw")
        # type
        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Type your name" if kind == "signature" else "Your initials")
        tl.addWidget(self.name)
        self.fonts = QListWidget()
        from PySide6.QtGui import QFontDatabase
        have = set(QFontDatabase.families())
        for f in [f for f in SCRIPT_FONTS if f in have] or ["Segoe UI", "Arial"]:
            it = QListWidgetItem(f)
            it.setFont(QFont(f, 20))
            self.fonts.addItem(it)
        self.fonts.setCurrentRow(0)
        self.name.textChanged.connect(self._preview_fonts)
        tl.addWidget(self.fonts)
        self.tabs.addTab(tw, "Type")
        # upload
        uw = QWidget()
        ul = QVBoxLayout(uw)
        self.up_lbl = label("Choose a photo/scan of your signature. The white background is removed automatically.",
                            "muted", True)
        ul.addWidget(self.up_lbl)
        self.up_path: str = ""
        ub = button("Choose image", "image")
        ub.clicked.connect(self._choose)
        ul.addWidget(ub, 0, Qt.AlignLeft)
        ul.addStretch(1)
        self.tabs.addTab(uw, "Upload")
        v.addWidget(self.tabs)
        row = QHBoxLayout()
        row.addWidget(label("Ink colour", "muted"))
        self.ink = QComboBox()
        self.ink.addItems(["Blue", "Black", "Red", "Green"])
        self.ink.currentTextChanged.connect(self._ink)
        row.addWidget(self.ink)
        row.addStretch(1)
        cancel = button("Cancel", "", "ghost")
        cancel.clicked.connect(self.reject)
        ok = button("Use this " + kind, "check", "primary")
        ok.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        v.addLayout(row)

    INKS = {"Blue": "#0B2A8C", "Black": "#111111", "Red": "#B3261E", "Green": "#0B6E3A"}

    def _ink(self, name):
        self.pad.color = QColor(self.INKS[name])
        self.pad.update()

    def _preview_fonts(self, text):
        for i in range(self.fonts.count()):
            it = self.fonts.item(i)
            it.setText(text or it.font().family())

    def _choose(self):
        f, _ = QFileDialog.getOpenFileName(self, "Signature image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if f:
            self.up_path = f
            self.up_lbl.setText(Path(f).name)

    def _accept(self):
        dest = paths.sub("signatures") / f"{self.kind}_{int(time.time() * 1000)}.png"
        tab = self.tabs.currentIndex()
        try:
            if tab == 0:
                if self.pad.to_png(dest) is None:
                    error_box(self, "Draw your " + self.kind + " first.")
                    return
            elif tab == 1:
                text = self.name.text().strip()
                if not text:
                    error_box(self, "Type your name first.")
                    return
                fam = self.fonts.currentItem().font().family() if self.fonts.currentItem() else "Segoe Script"
                f = QFont(fam, 64)
                from PySide6.QtGui import QFontMetrics
                fm = QFontMetrics(f)
                w, h = fm.horizontalAdvance(text) + 40, fm.height() + 20
                pm = QPixmap(w, h)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                p.setFont(f)
                p.setPen(QColor(self.INKS[self.ink.currentText()]))
                p.drawText(20, 10 + fm.ascent(), text)
                p.end()
                pm.save(str(dest), "PNG")
            else:
                if not self.up_path:
                    error_box(self, "Choose an image first.")
                    return
                remove_background(Path(self.up_path), dest, self.INKS[self.ink.currentText()]
                                  if self.ink.currentText() != "Black" else None)
        except Exception as e:  # noqa: BLE001
            error_box(self, str(e))
            return
        self.result_path = dest
        sigs = [s for s in paths.settings.get("signatures", []) if Path(s).exists()]
        paths.settings["signatures"] = [str(dest)] + sigs[:11]
        paths.settings.save()
        self.accept()


def remove_background(src: Path, dest: Path, recolor: str | None = None) -> Path:
    """Make paper transparent, crop to the ink, optionally recolour the ink."""
    import numpy as np
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    g = np.asarray(ImageOps.autocontrast(im.convert("L"), cutoff=2), dtype=np.float32)
    alpha = np.clip((215 - g) / 120 * 255, 0, 255).astype(np.uint8)
    rgba = np.dstack([np.asarray(im), alpha])
    if recolor:
        c = QColor(recolor)
        rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2] = c.red(), c.green(), c.blue()
    out = Image.fromarray(rgba, "RGBA")
    bbox = out.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    if bbox:
        out = out.crop(bbox)
    out.save(dest, "PNG")
    return dest


class SignPage(EditorBase):
    tool_id = "sign"
    save_text = "Sign & save"

    def build_panel(self):
        self.panel.addWidget(label("Your signature", "h2"))
        self.sigs = QListWidget()
        self.sigs.setIconSize(QSize(220, 60))
        self.sigs.setFixedHeight(170)
        self.panel.addWidget(self.sigs)
        row = QHBoxLayout()
        new_sig = button("New signature", "sign")
        new_sig.clicked.connect(lambda: self._new("signature"))
        new_ini = button("Initials", "plus")
        new_ini.clicked.connect(lambda: self._new("initials"))
        row.addWidget(new_sig)
        row.addWidget(new_ini)
        self.panel.addLayout(row)
        self.panel.addWidget(sep())
        self.panel.addWidget(label("Click a button, then click on the page", "faint", True))
        self.pending = None
        for key, text, icon in (("sig", "Place signature", "sign"), ("date", "Add date", "date"),
                                ("name", "Add name / text", "user"), ("check", "Add check mark ✓", "check")):
            b = button(text, icon)
            b.clicked.connect(lambda _=False, k=key: self._arm(k))
            self.panel.addWidget(b)
        self.date_fmt = QComboBox()
        self.date_fmt.addItems(["%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%m/%d/%Y"])
        self.panel.addWidget(self.date_fmt)
        dele = button("Remove selected", "trash", "ghost")
        dele.clicked.connect(lambda: self.canvas.remove_item(self.canvas.selected))
        self.panel.addWidget(dele)
        self.all_pages = QCheckBox("Put the selected item on every page")
        self.panel.addWidget(self.all_pages)
        self.canvas.clicked.connect(self._place)
        self.canvas.edit_requested.connect(self._edit_text)
        self._load_sigs()

    def _load_sigs(self):
        self.sigs.clear()
        for s in paths.settings.get("signatures", []):
            if Path(s).exists():
                it = QListWidgetItem(QIcon(QPixmap(s)), "")
                it.setData(Qt.UserRole, s)
                it.setSizeHint(QSize(240, 66))
                self.sigs.addItem(it)
        if self.sigs.count():
            self.sigs.setCurrentRow(0)

    def _new(self, kind):
        d = SignatureDialog(self, kind)
        if d.exec() and d.result_path:
            self._load_sigs()
            self._arm("sig")

    def _arm(self, key):
        if key == "sig" and not self.sigs.currentItem():
            self._new("signature")
            return
        self.pending = key
        self.canvas.set_mode("place")
        if self.main is not None:
            self.main.toast.show_message("Click on the page where it should go", "info")

    def _place(self, x, y):
        k = self.pending
        if k == "sig" and self.sigs.currentItem():
            path = self.sigs.currentItem().data(Qt.UserRole)
            pm = QPixmap(path)
            w = 150.0
            h = w * pm.height() / max(1, pm.width())
            self.canvas.add_item({"type": "image", "path": path, "x": x - w / 2, "y": y - h / 2, "w": w, "h": h,
                                  "keep_ratio": True})
        elif k == "date":
            self.canvas.add_item({"type": "text", "x": x, "y": y - 7, "text": date.today().strftime(
                self.date_fmt.currentText()), "size": 12, "color": "#111111"})
        elif k == "name":
            text, ok = QInputDialog.getText(self, "Add text", "Text (e.g. your full name, title):")
            if ok and text.strip():
                self.canvas.add_item({"type": "text", "x": x, "y": y - 7, "text": text, "size": 12,
                                      "color": "#111111"})
        elif k == "check":
            self.canvas.add_item({"type": "text", "x": x - 6, "y": y - 9, "text": "✓", "size": 18,
                                  "color": "#0B2A8C", "bold": True})
        self.pending = None
        self.canvas.set_mode("select")

    def _edit_text(self, it):
        if it.get("type") == "text":
            text, ok = QInputDialog.getText(self, "Edit text", "Text:", QLineEdit.Normal, it.get("text", ""))
            if ok:
                it["text"] = text
                self.canvas.update()

    def save(self):
        ops = self.canvas.ops()
        if not any(o["type"] == "image" for o in ops) and not ops:
            error_box(self, "Place your signature on the page first.")
            return
        sel = self.canvas.selected
        if self.all_pages.isChecked() and sel is not None and self.doc:
            base = {k: v for k, v in sel.items() if not k.startswith("_")}
            ops += [dict(base, page=i) for i in range(self.doc.n) if i != sel.get("page")]
        self.run_save(E.apply_edits, self.work, self.out_path("signed"), ops, done_msg="Signed")


# ===================================================================== Redact
class RedactPage(EditorBase):
    tool_id = "redact"
    save_text = "Redact & save"

    def build_panel(self):
        self.panel.addWidget(label("Find text to redact", "h2"))
        self.terms = QPlainTextEdit()
        self.terms.setPlaceholderText("Words or phrases, one per line")
        self.terms.setFixedHeight(80)
        self.terms.setStyleSheet("font-size: 13px; padding: 8px;")
        self.panel.addWidget(self.terms)
        from ..core.textlayer import PRESETS
        self.presets = {}
        for name in PRESETS:
            cb = QCheckBox(name)
            self.presets[name] = cb
            self.panel.addWidget(cb)
        self.case = QCheckBox("Match upper/lower case exactly")
        self.panel.addWidget(self.case)
        fb = button("Find & mark", "search")
        fb.clicked.connect(self.find)
        self.panel.addWidget(fb)
        self.panel.addWidget(sep())
        self.mark = button("Mark an area by hand", "rect")
        self.mark.setCheckable(True)
        self.mark.toggled.connect(lambda on: self.canvas.set_mode("rect" if on else "select"))
        self.panel.addWidget(self.mark)
        row = QHBoxLayout()
        dele = button("Unmark selected", "x", "ghost")
        dele.clicked.connect(lambda: self.canvas.remove_item(self.canvas.selected))
        clr = button("Clear all", "trash", "ghost")
        clr.clicked.connect(self.clear)
        row.addWidget(dele)
        row.addWidget(clr)
        self.panel.addLayout(row)
        self.count = label("No areas marked", "muted")
        self.panel.addWidget(self.count)
        self.keep = QCheckBox("Keep the rest of the text searchable")
        self.keep.setChecked(True)
        self.panel.addWidget(self.keep)
        self.meta = QCheckBox("Also remove hidden info (metadata)")
        self.meta.setChecked(True)
        self.panel.addWidget(self.meta)
        self.panel.addWidget(label("Redaction is permanent in the saved copy: marked content is removed, not just "
                                   "covered. Your original file is not changed.", "faint", True))
        self.canvas.rect_drawn.connect(lambda x, y, w, h: self.canvas.add_item(
            {"type": "redact", "x": x, "y": y, "w": w, "h": h}, select=False))
        self.canvas.items_changed.connect(self._count)

    def clear(self):
        self.canvas.items = []
        self.canvas.update()
        self._count()

    def _count(self):
        n = len(self.canvas.items)
        pages = len({it["page"] for it in self.canvas.items})
        self.count.setText(f"{n} area{'s' if n != 1 else ''} marked on {pages} page{'s' if pages != 1 else ''}"
                           if n else "No areas marked")

    def find(self):
        if not self.doc:
            return
        terms = [t for t in self.terms.toPlainText().splitlines() if t.strip()]
        presets = [k for k, cb in self.presets.items() if cb.isChecked()]
        if not terms and not presets:
            error_box(self, "Type something to find or tick a category.")
            return
        self.busy.start("Searching…")

        def done(found):
            self.busy.done()
            n = 0
            for i, rects in found.items():
                for r in rects:
                    x, y, w, h = self.doc.to_top_left(i, r)
                    self.canvas.add_item({"type": "redact", "page": i, "x": x, "y": y, "w": w, "h": h}, select=False)
                    n += 1
            self._count()
            if found:
                self.goto(min(found))
            if self.main is not None:
                self.main.toast.show_message(f"Marked {n} match{'es' if n != 1 else ''}" if n else "Nothing found",
                                             "ok" if n else "info")

        def fail(msg):
            self.busy.done()
            error_box(self, msg)
        run_bg(self, S.find_matches, self.work, terms, presets, "all", not self.case.isChecked(), on_done=done,
               on_fail=fail)

    def save(self):
        if not self.canvas.items:
            error_box(self, "Mark something to redact first.")
            return
        areas: dict[int, list] = {}
        for it in self.canvas.items:
            areas.setdefault(it["page"], []).append(self.doc.to_pdf_rect(it["page"], it["x"], it["y"], it["w"],
                                                                         it["h"]))
        self.run_save(S.redact_file, self.work, self.out_path("redacted"), areas, 200, self.keep.isChecked(),
                      self.meta.isChecked(), done_msg="Redacted")


# ===================================================================== Crop
class CropPage(EditorBase):
    tool_id = "crop"
    save_text = "Crop & save"

    def build_panel(self):
        self.panel.addWidget(label("Crop area", "h2"))
        self.panel.addWidget(label("Drag on the page to draw the area to keep. Move or resize it afterwards.",
                                   "muted", True))
        auto = button("Detect content automatically", "spark")
        auto.clicked.connect(self.auto)
        self.panel.addWidget(auto)
        reset = button("Reset", "x", "ghost")
        reset.clicked.connect(self.reset)
        self.panel.addWidget(reset)
        self.panel.addWidget(sep())
        self.panel.addWidget(label("Apply to", "muted"))
        self.scope = QComboBox()
        self.scope.addItems(["All pages", "This page only", "Odd pages", "Even pages", "Custom pages…"])
        self.panel.addWidget(self.scope)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("e.g. 1-3, 7")
        self.custom.hide()
        self.scope.currentTextChanged.connect(lambda t: self.custom.setVisible(t.startswith("Custom")))
        self.panel.addWidget(self.custom)
        self.auto_each = QCheckBox("Auto-trim each page separately")
        self.panel.addWidget(self.auto_each)
        self.info = label("", "faint", True)
        self.panel.addWidget(self.info)
        self.canvas.set_mode("rect")
        self.canvas.rect_drawn.connect(self._set_rect)
        self.canvas.items_changed.connect(self._info)

    def after_load(self):
        self.reset()

    def _crop_item(self):
        return next((it for it in self.canvas.items if it.get("type") == "crop"), None)

    def _set_rect(self, x, y, w, h):
        it = self._crop_item()
        if it is None:
            self.canvas.add_item({"type": "crop", "x": x, "y": y, "w": w, "h": h})
        else:
            it.update(x=x, y=y, w=w, h=h, page=self.canvas.page)
            self.canvas.selected = it
        self.canvas.set_mode("select")
        self.canvas.update()
        self._info()

    def reset(self):
        self.canvas.items = []
        self.canvas.set_mode("rect")
        self.canvas.update()
        self._info()

    def auto(self):
        if not self.doc:
            return
        try:
            with pdfium_lock():
                bb = E.content_bbox(self.work, self.canvas.page)
        except Exception as e:  # noqa: BLE001
            error_box(self, str(e))
            return
        if bb:
            l, b, r, t = bb
            H = self.doc.size(self.canvas.page)[1]
            self._set_rect(l, H - t, r - l, t - b)

    def goto(self, i):
        super().goto(i)
        it = self._crop_item() if hasattr(self, "scope") else None
        if it is not None:
            it["page"] = i                      # the crop box follows you between pages
            self.canvas.update()

    def _info(self):
        it = self._crop_item()
        if it is None:
            self.info.setText("No area selected yet.")
            return
        mm = 25.4 / 72
        self.info.setText(f"Area: {it['w'] * mm:.0f} × {it['h'] * mm:.0f} mm")

    def save(self):
        it = self._crop_item()
        if it is None and not self.auto_each.isChecked():
            error_box(self, "Draw the area to keep first (or tick auto-trim).")
            return
        n = self.doc.n
        scope = self.scope.currentText()
        cur = self.canvas.page
        if scope.startswith("This"):
            idx = [cur]
        elif scope.startswith("Odd"):
            idx = parse_pages("odd", n)
        elif scope.startswith("Even"):
            idx = parse_pages("even", n)
        elif scope.startswith("Custom"):
            try:
                idx = parse_pages(self.custom.text(), n)
            except ValueError as e:
                error_box(self, str(e))
                return
        else:
            idx = list(range(n))
        rect = dict(it) if it else None
        work, dest, auto_each = self.work, self.out_path("cropped"), self.auto_each.isChecked()

        def job():
            from ..core.util import open_pdf
            pdf = open_pdf(work)
            for i in idx:
                page = pdf.pages[i]
                if auto_each:
                    bb = E.content_bbox(work, i)
                    if bb:
                        E.set_visual_crop(page, *bb)
                    continue
                H = E.visual_size(page)[1]
                E.set_visual_crop(page, rect["x"], H - rect["y"] - rect["h"], rect["x"] + rect["w"], H - rect["y"])
            return save(pdf, dest)
        self.run_save(job, done_msg="Cropped")


# ===================================================================== Forms
FIELD_TYPES = [("text", "Text field", "text"), ("multiline", "Text box (multi-line)", "note"),
               ("checkbox", "Checkbox", "check"), ("choice", "Dropdown list", "queue")]


class FormsPage(EditorBase):
    tool_id = "forms"
    save_text = "Save form"

    def build_panel(self):
        self.tabs = QTabWidget()
        # fill tab
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(0, 8, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Field", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        fl.addWidget(self.table)
        self.fill_info = label("", "faint", True)
        fl.addWidget(self.fill_info)
        self.tabs.addTab(fw, "Fill in")
        # create tab
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 8, 0, 0)
        det = button("Detect fields automatically", "spark")
        det.clicked.connect(self.detect)
        cl.addWidget(det)
        cl.addWidget(label("Or pick a field type and drag on the page:", "faint", True))
        self.ftype = "text"
        grp = QButtonGroup(self)
        for key, text, icon in FIELD_TYPES:
            b = QPushButton(f"  {text}")
            b.setObjectName("toolbtn")
            b.setIcon(T.icon(icon, T.TEXT, 18))
            b.setCheckable(True)
            grp.addButton(b)
            cl.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self._arm(k))
        self.newlist = QListWidget()
        self.newlist.setFixedHeight(120)
        self.newlist.itemDoubleClicked.connect(self._rename)
        cl.addWidget(self.newlist)
        row = QHBoxLayout()
        ren = button("Rename", "edit", "ghost")
        ren.clicked.connect(lambda: self.newlist.currentItem() and self._rename(self.newlist.currentItem()))
        dele = button("Delete", "trash", "ghost")
        dele.clicked.connect(self._delete)
        row.addWidget(ren)
        row.addWidget(dele)
        cl.addLayout(row)
        self.tabs.addTab(cw, "Create")
        self.panel.addWidget(self.tabs, 1)
        self.flat = QCheckBox("Flatten (make the answers part of the page)")
        self.panel.addWidget(self.flat)
        self.canvas.rect_drawn.connect(self._drawn)
        self.canvas.items_changed.connect(self._refresh_new)

    def _arm(self, k):
        self.ftype = k
        self.canvas.set_mode("rect")

    def after_load(self):
        self.fields = []
        try:
            self.fields = E.list_fields(self.work)
        except Exception:
            self.fields = []
        self.table.setRowCount(0)
        self.editors = {}
        for f in self.fields:
            if f["type"] == "signature":
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            name_item = QTableWidgetItem(f["name"])
            name_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, name_item)
            if f["type"] == "checkbox":
                w = QCheckBox()
                w.setChecked(f["value"] not in ("", "/Off", "Off"))
            elif f["type"] in ("choice", "radio"):
                w = QComboBox()
                opts = [o.lstrip("/") for o in f["options"]]
                w.addItems([""] + opts)
                w.setCurrentText(f["value"].lstrip("/"))
            else:
                w = QLineEdit(f["value"])
            self.table.setCellWidget(r, 1, w)
            self.editors[f["name"]] = (f, w)
            i = f["page"]
            if f.get("rect") and 0 <= i < self.doc.n:
                x, y, w_, h = self.doc.to_top_left(i, f["rect"])
                self.canvas.add_item({"type": "field", "page": i, "x": x, "y": y, "w": w_, "h": h, "name": f["name"],
                                      "ftype": f["type"], "_locked": True}, select=False)
        self.table.resizeColumnToContents(0)
        n = len(self.editors)
        self.fill_info.setText(f"{n} fillable field{'s' if n != 1 else ''} found." if n else
                               "This PDF has no fillable fields yet - use Create to add some.")
        self.tabs.setCurrentIndex(0 if n else 1)
        self._refresh_new()

    def _drawn(self, x, y, w, h):
        k = self.ftype
        if k == "checkbox":
            w = h = min(max(w, 10), 18)
        n = sum(1 for it in self.canvas.items if not it.get("_locked")) + 1
        name, ok = QInputDialog.getText(self, "Field name", "Name for this field:", QLineEdit.Normal, f"{k}{n}")
        if not ok:
            return
        it = {"type": "field", "x": x, "y": y, "w": w, "h": h, "name": name.strip() or f"{k}{n}", "ftype": k}
        if k == "choice":
            opts, ok2 = QInputDialog.getMultiLineText(self, "Dropdown options", "One option per line:",
                                                      "Option 1\nOption 2")
            it["options"] = [o for o in opts.splitlines() if o.strip()] if ok2 else []
        self.canvas.add_item(it)

    def detect(self):
        if not self.doc:
            return
        try:
            with pdfium_lock():
                found = E.detect_fields(self.work)
        except Exception as e:  # noqa: BLE001
            error_box(self, str(e))
            return
        for k, f in enumerate(found):
            x, y, w, h = f["rect"]
            self.canvas.add_item({"type": "field", "page": f["page"], "x": x, "y": y, "w": w, "h": h,
                                  "name": f"{f['type']}{k + 1}", "ftype": f["type"]}, select=False)
        if self.main is not None:
            self.main.toast.show_message(f"Found {len(found)} field{'s' if len(found) != 1 else ''}",
                                         "ok" if found else "info")

    def _new_items(self):
        return [it for it in self.canvas.items if it.get("type") == "field" and not it.get("_locked")]

    def _refresh_new(self):
        self.newlist.clear()
        for it in self._new_items():
            li = QListWidgetItem(T.icon(dict((k, i) for k, _t, i in FIELD_TYPES).get(it["ftype"], "text"),
                                        T.MUTED, 16), f"p{it['page'] + 1}  {it['name']}")
            li.setData(Qt.UserRole, id(it))
            self.newlist.addItem(li)

    def _find(self, li):
        return next((it for it in self._new_items() if id(it) == li.data(Qt.UserRole)), None)

    def _rename(self, li):
        it = self._find(li)
        if it is None:
            return
        name, ok = QInputDialog.getText(self, "Rename field", "Name:", QLineEdit.Normal, it["name"])
        if ok and name.strip():
            it["name"] = name.strip()
            self._refresh_new()
            self.canvas.update()

    def _delete(self):
        li = self.newlist.currentItem()
        if li is not None:
            self.canvas.remove_item(self._find(li))

    def save(self):
        values = {}
        for name, (f, w) in getattr(self, "editors", {}).items():
            if isinstance(w, QCheckBox):
                values[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                values[name] = ("/" + w.currentText()) if f["type"] == "radio" and w.currentText() else w.currentText()
            else:
                values[name] = w.text()
        new = [{"type": it["ftype"], "name": it["name"], "page": it["page"], "rect": (it["x"], it["y"], it["w"],
                it["h"]), "options": it.get("options", [])} for it in self._new_items()]
        if not values and not new:
            error_box(self, "Add some fields (Create tab) or open a PDF that has a form.")
            return
        work, dest, flat = self.work, self.out_path("form"), self.flat.isChecked()

        def job():
            import tempfile
            src = work
            if new:
                tmp = Path(tempfile.mkdtemp()) / "fields.pdf"
                E.add_fields(src, tmp, new)
                src = tmp
            changed = {k: v for k, v in values.items() if v not in ("", False)}
            if changed or flat:
                return E.fill_fields(src, dest, changed, flatten=flat)
            import shutil
            shutil.copy2(src, dest)
            return dest
        self.run_save(job, done_msg="Form saved")


PAGES = {"edit": EditPage, "sign": SignPage, "redact": RedactPage, "crop": CropPage, "forms": FormsPage}
