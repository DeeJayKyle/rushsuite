"""Interactive page view used by the Edit, Sign, Redact, Crop and Forms screens.

All item geometry is in *visual top-left points* (x right, y down, as the page is displayed) - the same
convention core.edit.apply_edits uses."""
from __future__ import annotations

import copy
from collections import OrderedDict
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..core.util import PDFIUM_LOCK, pdfium_lock, rect_to_visual, visual_size
from .widgets import pil_to_pixmap

HANDLE = 9


class PdfDoc:
    """A PDF opened for viewing: page sizes (visual points) + cached renders."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.pdf = pikepdf.open(str(path))
        with pdfium_lock():
            self.doc = pdfium.PdfDocument(str(path))
        self.busy = False
        self.n = len(self.doc)
        self.sizes = [visual_size(p) for p in self.pdf.pages]
        self._cache: OrderedDict = OrderedDict()

    def size(self, i: int) -> tuple[float, float]:
        return self.sizes[i]

    def render(self, i: int, scale: float) -> QPixmap:
        key = (i, round(scale, 3))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if not PDFIUM_LOCK.acquire(timeout=0.03):     # a background job is using PDFium: show what we have
            self.busy = True
            near = [v for k, v in self._cache.items() if k[0] == i]
            if near:
                return near[-1]
            w, h = self.sizes[i]
            pm = QPixmap(max(1, int(w * scale)), max(1, int(h * scale)))
            pm.fill(QColor("#FFFFFF"))
            return pm
        try:
            page = self.doc[i]
            img = page.render(scale=scale, may_draw_forms=True).to_pil()
            page.close()
        finally:
            PDFIUM_LOCK.release()
        self.busy = False
        pm = pil_to_pixmap(img)
        self._cache[key] = pm
        while len(self._cache) > 24:
            self._cache.popitem(last=False)
        return pm

    def thumb(self, i: int, width: int = 120) -> QPixmap:
        w, _h = self.sizes[i]
        return self.render(i, width / max(1.0, w))

    def to_top_left(self, i: int, rect) -> tuple[float, float, float, float]:
        """Unrotated PDF rect (x0, y0, x1, y1) -> visual top-left (x, y, w, h)."""
        l, b, r, t = rect_to_visual(self.pdf.pages[i], rect)
        H = self.sizes[i][1]
        return l, H - t, r - l, t - b

    def to_pdf_rect(self, i: int, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
        """Visual top-left (x, y, w, h) -> unrotated PDF rect (x0, y0, x1, y1)."""
        from ..core.edit import from_visual
        page = self.pdf.pages[i]
        H = self.sizes[i][1]
        a = from_visual(page, x, H - y - h)
        b = from_visual(page, x + w, H - y)
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def close(self):
        try:
            with pdfium_lock():
                self.doc.close()
            self.pdf.close()
        except Exception:
            pass


def item_bounds(it: dict) -> QRectF:
    t = it.get("type")
    if t == "line":
        x1, y1, x2, y2 = it["x1"], it["y1"], it["x2"], it["y2"]
        return QRectF(min(x1, x2) - 3, min(y1, y2) - 3, abs(x2 - x1) + 6, abs(y2 - y1) + 6)
    if t == "ink":
        pts = [p for s in it.get("points", []) for p in s]
        if not pts:
            return QRectF()
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return QRectF(min(xs) - 3, min(ys) - 3, max(xs) - min(xs) + 6, max(ys) - min(ys) + 6)
    if t == "text":
        lines = str(it.get("text", "")).split("\n")
        size = float(it.get("size", 14))
        f = QFont()
        f.setPixelSize(max(1, int(round(size))))
        f.setBold(bool(it.get("bold")))
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(f)
        w = max((fm.horizontalAdvance(ln) for ln in lines), default=10) + 4
        return QRectF(it["x"], it["y"], max(w, 10), size * len(lines) + 2)
    return QRectF(it.get("x", 0), it.get("y", 0), it.get("w", 0), it.get("h", 0))


def move_item(it: dict, dx: float, dy: float) -> None:
    t = it.get("type")
    if t == "line":
        it["x1"] += dx
        it["x2"] += dx
        it["y1"] += dy
        it["y2"] += dy
    elif t == "ink":
        it["points"] = [[(p[0] + dx, p[1] + dy) for p in s] for s in it["points"]]
    else:
        it["x"] = it.get("x", 0) + dx
        it["y"] = it.get("y", 0) + dy


class PageCanvas(QWidget):
    """Shows one page and its overlay items; modes: select | rect | line | ink | place | none."""
    rect_drawn = Signal(float, float, float, float)       # x, y, w, h (points)
    line_drawn = Signal(float, float, float, float)
    ink_drawn = Signal(list)                              # [(x, y), ...]
    clicked = Signal(float, float)
    selection_changed = Signal(object)                    # item or None
    edit_requested = Signal(object)
    items_changed = Signal()

    def __init__(self):
        super().__init__()
        self.doc: PdfDoc | None = None
        self.page = 0
        self.zoom = 1.3
        self.mode = "select"
        self.items: list[dict] = []          # all pages; each has 'page'
        self.selected: dict | None = None
        self.draw_color = QColor("#FF5A5F")
        self._drag = None                     # ('move'|'resize'|'new'|'ink', start_pt, orig)
        self._cur = None
        self._ink: list = []
        self._imgcache: dict = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------ state
    def set_doc(self, doc: PdfDoc | None):
        self.doc = doc
        self.page = 0
        self.selected = None
        self._relayout()

    def set_page(self, i: int):
        if self.doc and 0 <= i < self.doc.n:
            self.page = i
            self.selected = None
            self.selection_changed.emit(None)
            self._relayout()

    def set_zoom(self, z: float):
        self.zoom = max(0.3, min(4.0, z))
        self._relayout()

    def fit_width(self, avail: int):
        if self.doc:
            w, _h = self.doc.size(self.page)
            self.set_zoom((avail - 40) / max(1.0, w))

    def set_mode(self, mode: str):
        self.mode = mode
        self.setCursor(QCursor(Qt.ArrowCursor if mode in ("select", "none") else Qt.CrossCursor))

    def _relayout(self):
        if self.doc:
            w, h = self.doc.size(self.page)
            self.setFixedSize(int(w * self.zoom) + 2, int(h * self.zoom) + 2)
        else:
            self.setFixedSize(10, 10)
        self.update()

    def page_items(self) -> list[dict]:
        return [it for it in self.items if it.get("page") == self.page]

    def add_item(self, it: dict, select: bool = True):
        it = dict(it)
        it.setdefault("page", self.page)
        self.items.append(it)
        if select:
            self.selected = it
            self.selection_changed.emit(it)
        self.items_changed.emit()
        self.update()
        return it

    def remove_item(self, it: dict | None):
        if it is not None and it in self.items:
            self.items.remove(it)
            if self.selected is it:
                self.selected = None
                self.selection_changed.emit(None)
            self.items_changed.emit()
            self.update()

    def ops(self, kinds: tuple | None = None) -> list[dict]:
        out = []
        for it in self.items:
            if kinds and it.get("type") not in kinds:
                continue
            d = {k: v for k, v in it.items() if not k.startswith("_")}
            out.append(copy.deepcopy(d))
        return out

    # ------------------------------------------------------------------ coords
    def _pt(self, pos) -> tuple[float, float]:
        return pos.x() / self.zoom, pos.y() / self.zoom

    def _hit(self, x: float, y: float) -> tuple[dict | None, bool]:
        for it in reversed(self.page_items()):
            if it.get("_locked"):
                continue
            r = item_bounds(it)
            hs = HANDLE / self.zoom
            if it.get("type") not in ("line", "ink", "text") and abs(x - r.right()) < hs and abs(y - r.bottom()) < hs:
                return it, True
            if r.adjusted(-2, -2, 2, 2).contains(QPointF(x, y)):
                return it, False
        return None, False

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        if not self.doc or e.button() != Qt.LeftButton:
            return
        x, y = self._pt(e.position())
        self.setFocus()
        if self.mode == "select":
            it, handle = self._hit(x, y)
            self.selected = it
            self.selection_changed.emit(it)
            if it is not None:
                self._drag = ("resize" if handle else "move", (x, y), copy.deepcopy(it))
            self.update()
        elif self.mode in ("rect", "line"):
            self._drag = ("new", (x, y), None)
            self._cur = (x, y, x, y)
        elif self.mode == "ink":
            self._drag = ("ink", (x, y), None)
            self._ink = [(x, y)]
        elif self.mode == "place":
            self.clicked.emit(x, y)

    def mouseMoveEvent(self, e):
        if not self.doc:
            return
        x, y = self._pt(e.position())
        if self._drag is None:
            if self.mode == "select":
                it, handle = self._hit(x, y)
                self.setCursor(QCursor(Qt.SizeFDiagCursor if handle else Qt.SizeAllCursor if it else Qt.ArrowCursor))
            return
        kind, (sx, sy), orig = self._drag
        if kind == "move" and self.selected is not None:
            cur = self.selected
            for k in ("x", "y", "x1", "y1", "x2", "y2", "points"):
                if k in orig:
                    cur[k] = copy.deepcopy(orig[k])
            move_item(cur, x - sx, y - sy)
        elif kind == "resize" and self.selected is not None:
            cur = self.selected
            w = max(6.0, orig.get("w", 0) + x - sx)
            h = max(6.0, orig.get("h", 0) + y - sy)
            if cur.get("keep_ratio") and orig.get("w") and orig.get("h"):
                h = w * orig["h"] / orig["w"]
            cur["w"], cur["h"] = w, h
        elif kind == "new":
            self._cur = (sx, sy, x, y)
        elif kind == "ink":
            self._ink.append((x, y))
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        kind, (sx, sy), _orig = self._drag
        self._drag = None
        x, y = self._pt(e.position())
        if kind == "new":
            self._cur = None
            if self.mode == "line":
                if abs(x - sx) + abs(y - sy) > 3:
                    self.line_drawn.emit(sx, sy, x, y)
            elif abs(x - sx) > 4 and abs(y - sy) > 4:
                self.rect_drawn.emit(min(sx, x), min(sy, y), abs(x - sx), abs(y - sy))
            elif self.mode == "rect":
                self.clicked.emit(x, y)
        elif kind == "ink":
            if len(self._ink) > 1:
                self.ink_drawn.emit(list(self._ink))
            self._ink = []
        else:
            self.items_changed.emit()
        self.update()

    def mouseDoubleClickEvent(self, e):
        x, y = self._pt(e.position())
        it, _h = self._hit(x, y)
        if it is not None:
            self.edit_requested.emit(it)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected is not None:
            self.remove_item(self.selected)
        elif self.selected is not None and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 5 if e.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(e.key(), 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(e.key(), 0)
            move_item(self.selected, dx, dy)
            self.items_changed.emit()
            self.update()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------ paint
    def _image(self, path: str) -> QPixmap:
        if path not in self._imgcache:
            self._imgcache[path] = QPixmap(path)
        return self._imgcache[path]

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.doc:
            return
        z = self.zoom
        pm = self.doc.render(self.page, z * self.devicePixelRatioF())
        if self.doc.busy:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, self.update)
        W, H = self.doc.size(self.page)
        p.drawPixmap(QRectF(0, 0, W * z, H * z), pm, QRectF(pm.rect()))
        p.scale(z, z)
        for it in self.page_items():
            self._paint_item(p, it)
        # in-progress shapes
        p.setBrush(Qt.NoBrush)
        if self._cur:
            x0, y0, x1, y1 = self._cur
            pen = QPen(self.draw_color, 1.2 / z, Qt.DashLine)
            p.setPen(pen)
            if self.mode == "line":
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            else:
                p.drawRect(QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)))
        if len(self._ink) > 1:
            p.setPen(QPen(self.draw_color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(QPointF(*self._ink[0]))
            for pt in self._ink[1:]:
                path.lineTo(QPointF(*pt))
            p.drawPath(path)
        if self.selected is not None and self.selected.get("page") == self.page:
            r = item_bounds(self.selected)
            p.setPen(QPen(QColor("#FF9F43"), 1.2 / z, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            if self.selected.get("type") not in ("line", "ink", "text"):
                hs = HANDLE / z
                p.setBrush(QColor("#FF9F43"))
                p.drawRect(QRectF(r.right() - hs / 2, r.bottom() - hs / 2, hs, hs))
        p.end()

    def _paint_item(self, p: QPainter, it: dict):
        t = it.get("type")
        col = QColor(it.get("color", "#D62828"))
        op = float(it.get("opacity", 1))
        p.save()
        p.setOpacity(op)
        if t == "text":
            f = QFont()
            f.setPixelSize(max(1, int(round(float(it.get("size", 14))))))
            f.setBold(bool(it.get("bold")))
            p.setFont(f)
            p.setPen(col)
            size = float(it.get("size", 14))
            for k, line in enumerate(str(it.get("text", "")).split("\n")):
                p.drawText(QPointF(it["x"], it["y"] + size * (k + 1) - size * 0.2), line)
        elif t == "image":
            img = self._image(it["path"])
            target = QRectF(it["x"], it["y"], it["w"], it["h"])
            if not img.isNull():
                if it.get("keep_ratio", True):
                    s = min(target.width() / img.width(), target.height() / img.height())
                    w, h = img.width() * s, img.height() * s
                    target = QRectF(target.center().x() - w / 2, target.center().y() - h / 2, w, h)
                p.drawPixmap(target, img, QRectF(img.rect()))
        elif t in ("rect", "ellipse"):
            p.setPen(QPen(col, float(it.get("width", 2))))
            p.setBrush(QBrush(QColor(it["fill"])) if it.get("fill") else Qt.NoBrush)
            r = QRectF(it["x"], it["y"], it["w"], it["h"])
            p.drawRect(r) if t == "rect" else p.drawEllipse(r)
        elif t == "highlight":
            p.setOpacity(float(it.get("opacity", 0.4)))
            p.fillRect(QRectF(it["x"], it["y"], it["w"], it["h"]), QColor(it.get("color", "#FFE14D")))
        elif t == "whiteout":
            p.fillRect(QRectF(it["x"], it["y"], it["w"], it["h"]), QColor("#FFFFFF"))
            p.setPen(QPen(QColor("#BBBBBB"), 0.5, Qt.DotLine))
            p.drawRect(QRectF(it["x"], it["y"], it["w"], it["h"]))
        elif t == "line":
            p.setPen(QPen(col, float(it.get("width", 2)), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(it["x1"], it["y1"]), QPointF(it["x2"], it["y2"]))
        elif t == "ink":
            p.setPen(QPen(col, float(it.get("width", 2)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            for s in it.get("points", []):
                if len(s) > 1:
                    path = QPainterPath(QPointF(*s[0]))
                    for pt in s[1:]:
                        path.lineTo(QPointF(*pt))
                    p.drawPath(path)
        elif t == "redact":
            r = QRectF(it["x"], it["y"], it["w"], it["h"])
            p.fillRect(r, QColor(0, 0, 0, 170))
            p.setPen(QPen(QColor("#FF5A5F"), 1))
            p.drawRect(r)
        elif t == "crop":
            W, H = self.doc.size(self.page)
            r = QRectF(it["x"], it["y"], it["w"], it["h"])
            shade = QColor(0, 0, 0, 120)
            p.fillRect(QRectF(0, 0, W, r.top()), shade)
            p.fillRect(QRectF(0, r.bottom(), W, H - r.bottom()), shade)
            p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
            p.fillRect(QRectF(r.right(), r.top(), W - r.right(), r.height()), shade)
            p.setPen(QPen(QColor("#FF9F43"), 1.5, Qt.DashLine))
            p.drawRect(r)
        elif t == "field":
            r = QRectF(it["x"], it["y"], it["w"], it["h"])
            existing = it.get("_locked")
            c = QColor("#4DA3FF" if not existing else "#3DDC97")
            fill = QColor(c)
            fill.setAlpha(40)
            p.fillRect(r, fill)
            p.setPen(QPen(c, 1, Qt.SolidLine if existing else Qt.DashLine))
            p.drawRect(r)
            f = QFont()
            f.setPixelSize(7)
            p.setFont(f)
            p.drawText(QPointF(r.left() + 1, r.top() - 1.5), f"{it.get('ftype', 'text')}: {it.get('name', '')}")
        p.restore()
