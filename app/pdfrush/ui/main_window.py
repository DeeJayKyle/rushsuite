"""Main window: sidebar + home grid of every tool + tool screens."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, paths
from ..core import load_all
from ..core.registry import CATEGORIES, TOOLS
from . import theme as T
from .widgets import FlowLayout, IconBadge, Page, Toast, button, card, label, open_path

CHIPS = ["All", "Workflows", "Organize PDF", "Optimize PDF", "Convert PDF", "Edit PDF", "PDF Security",
         "PDF Intelligence"]


class Tile(QFrame):
    clicked = Signal(str)

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self.setObjectName("tile")
        self.setFixedSize(236, 178)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tool.desc)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(IconBadge(tool.icon, tool.color, 44))
        top.addStretch(1)
        if tool.new:
            top.addWidget(label("NEW", "newpill"), 0, Qt.AlignTop)
        v.addLayout(top)
        v.addWidget(label(tool.name, "tiletitle"))
        d = label(tool.desc, "tiledesc", True)
        d.setMaximumHeight(52)
        v.addWidget(d)
        v.addStretch(1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.tool.id)


class WorkflowTile(Tile):
    def __init__(self):
        class _T:   # looks like a tool for the tile
            id, name, icon, color, new = "__workflows", "Create a workflow", "workflow", T.ACCENT, False
            desc = "Chain your favourite tools and run them on many files in one click."
        super().__init__(_T)


class HomePage(Page):
    def __init__(self, main):
        super().__init__("", "", max_width=1320)
        self.main = main
        hero = QVBoxLayout()
        hero.setSpacing(6)
        t = label("Every tool you need to work with PDFs", "h1")
        t.setAlignment(Qt.AlignCenter)
        s = label("Merge, split, compress, convert, rotate, unlock, sign, edit, OCR, translate and more - 100% on "
                  "your PC, fast and private.", "muted", True)
        s.setAlignment(Qt.AlignCenter)
        hero.addWidget(t)
        hero.addWidget(s)
        self.body.addLayout(hero)
        sr = QHBoxLayout()
        sr.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search tools…   (Ctrl+K)")
        self.search.addAction(T.icon("search", T.MUTED, 18), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedWidth(460)
        self.search.textChanged.connect(self.filter)
        sr.addWidget(self.search)
        sr.addStretch(1)
        self.body.addLayout(sr)

        chips = QFrame()
        chips.setObjectName("chipbar")
        cl = QHBoxLayout(chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addStretch(1)
        self.chip_group = QButtonGroup(self)
        for c in CHIPS:
            b = QPushButton(c)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.chip_group.addButton(b)
            cl.addWidget(b)
            b.clicked.connect(lambda _=False, c=c: self.set_chip(c))
        cl.addStretch(1)
        self.chip_group.buttons()[0].setChecked(True)
        self.chip = "All"
        self.body.addWidget(chips)

        holder = QWidget()
        self.flow = FlowLayout(holder, 16)
        self.tiles: list[Tile] = []
        order = {c: i for i, c in enumerate(CATEGORIES)}
        for tool in sorted(TOOLS.values(), key=lambda t: order.get(t.category, 99)):
            tile = Tile(tool)
            tile.clicked.connect(self.main.open_tool)
            self.flow.addWidget(tile)
            self.tiles.append(tile)
        self.wf_tile = WorkflowTile()
        self.wf_tile.clicked.connect(lambda _id: self.main.show_workflows())
        self.flow.addWidget(self.wf_tile)
        self.body.addWidget(holder)
        self.empty = label("No tool matches your search.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        self.body.addWidget(self.empty)
        tip = label("Tip: drop files anywhere on this window to pick a tool for them.", "faint")
        tip.setAlignment(Qt.AlignCenter)
        self.body.addWidget(tip)
        self.finish()

    def set_chip(self, c):
        self.chip = c
        self.filter()

    def filter(self, *_):
        q = self.search.text().strip().lower()
        shown = 0
        for tile in self.tiles:
            t = tile.tool
            cat_ok = (self.chip == "All" or t.category == self.chip or
                      (self.chip == "Convert PDF" and t.category.startswith("Convert")))
            if self.chip == "Workflows":
                cat_ok = False
            text_ok = not q or q in t.name.lower() or q in t.desc.lower() or q in t.category.lower()
            tile.setVisible(cat_ok and text_ok)
            shown += cat_ok and text_ok
        wf = self.chip in ("All", "Workflows") and (not q or "workflow" in q)
        self.wf_tile.setVisible(wf)
        self.empty.setVisible(shown == 0 and not wf)
        self.flow.invalidate()


class RecentPage(Page):
    def __init__(self, main):
        super().__init__("Recent", "Files PDFRush created lately.")
        self.main = main
        c, v = card()
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.itemDoubleClicked.connect(lambda it: open_path(it.data(Qt.UserRole), select=True))
        v.addWidget(self.list)
        row = QHBoxLayout()
        sh = button("Show in folder", "folder")
        sh.clicked.connect(lambda: self.list.currentItem() and open_path(self.list.currentItem().data(Qt.UserRole),
                                                                         select=True))
        use = button("Use with a tool…", "right")
        use.clicked.connect(self._use)
        clr = button("Clear list", "trash", "ghost")
        clr.clicked.connect(self._clear)
        row.addWidget(sh)
        row.addWidget(use)
        row.addStretch(1)
        row.addWidget(clr)
        v.addLayout(row)
        self.body.addWidget(c)
        self.finish()

    def refresh(self):
        self.list.clear()
        for r in paths.settings.get("recent", []):
            p = Path(r)
            if p.exists():
                it = QListWidgetItem(T.icon("pdf" if p.suffix.lower() == ".pdf" else "note", T.ACCENT2, 20),
                                     f"{p.name}    —    {p.parent}")
                it.setData(Qt.UserRole, str(p))
                self.list.addItem(it)
        if not self.list.count():
            self.list.addItem("Nothing yet - results you create will show up here.")

    def _use(self):
        it = self.list.currentItem()
        if it is not None and it.data(Qt.UserRole):
            self.main.pick_tool_for([Path(it.data(Qt.UserRole))])

    def _clear(self):
        paths.settings["recent"] = []
        paths.settings.save()
        self.refresh()


class MainWindow(QMainWindow):
    def __init__(self, files: list[str] | None = None):
        super().__init__()
        self.suite = None          # set by RushSuite
        load_all()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 880)
        self.setMinimumSize(1060, 680)
        icon_path = paths.ASSETS_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setAcceptDrops(True)
        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(224)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 20, 14, 16)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        brand.addWidget(IconBadge("pdf", T.ACCENT, 36))
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(18)
        self.nav_group = QButtonGroup(self)
        self.nav: dict[str, QPushButton] = {}
        for key, text, icon in (("home", "All tools", "grid"), ("workflows", "Workflows", "workflow"),
                                ("recent", "Recent", "clock"), ("settings", "Settings", "settings")):
            b = QPushButton(f"  {text}")
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setIcon(T.icon(icon, T.MUTED, 20))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_key(k))
            self.nav_group.addButton(b)
            self.nav[key] = b
            sv.addWidget(b)
        sv.addSpacing(16)
        sv.addWidget(label("POPULAR", "faint"))
        for tid in ("merge", "compress", "pdf_to_word", "edit", "sign", "ocr_pdf"):
            t = TOOLS.get(tid)
            if t is None:
                continue
            b = QPushButton(f"  {t.name}")
            b.setObjectName("nav")
            b.setIcon(T.icon(t.icon, t.color, 18))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, tid=tid: self.open_tool(tid))
            sv.addWidget(b)
        sv.addStretch(1)
        sv.addWidget(label(f"v{__version__} · offline", "faint"))
        h.addWidget(side)

        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.pages: dict[str, QWidget] = {}
        self.home = HomePage(self)
        self._add("home", self.home)
        self.toast = Toast(self.centralWidget())
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+Home"), self, activated=lambda: self.show_key("home"))
        self.show_key("home")
        T.dark_title_bar(self)
        if files:
            fs = [Path(f) for f in files if Path(f).exists()]
            if fs:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(400, lambda: self.pick_tool_for(fs))

    # ------------------------------------------------------------------ navigation
    def _add(self, key, w):
        self.pages[key] = w
        self.stack.addWidget(w)
        return w

    def _page(self, key):
        if key in self.pages:
            return self.pages[key]
        if key == "workflows":
            from .workflows_page import WorkflowsPage
            return self._add(key, WorkflowsPage(self))
        if key == "recent":
            return self._add(key, RecentPage(self))
        if key == "settings":
            from .settings_page import SettingsPage
            return self._add(key, SettingsPage(self))
        tool = TOOLS[key]
        if tool.page == "organize":
            from .organize_page import OrganizePage
            return self._add(key, OrganizePage(self))
        if tool.page == "compare":
            from .compare_page import ComparePage
            return self._add(key, ComparePage(self))
        if tool.page in ("edit", "sign", "redact", "crop", "forms"):
            from .editor_pages import PAGES
            return self._add(key, PAGES[tool.page](self))
        from .tool_page import ToolPage
        return self._add(key, ToolPage(tool, self))

    def show_key(self, key):
        page = self._page(key)
        if key == "recent":
            page.refresh()
        self.stack.setCurrentWidget(page)
        self.nav_group.setExclusive(False)
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.nav_group.setExclusive(True)

    def show_workflows(self):
        self.show_key("workflows")

    def open_tool(self, tool_id: str, files: list | None = None):
        if tool_id == "__workflows":
            self.show_workflows()
            return
        if tool_id not in TOOLS:
            return
        page = self._page(tool_id)
        self.show_key(tool_id)
        if files and hasattr(page, "set_files"):
            page.set_files([Path(f) for f in files])

    def _focus_search(self):
        self.show_key("home")
        self.home.search.setFocus()
        self.home.search.selectAll()

    # ------------------------------------------------------------------ drop anywhere
    def pick_tool_for(self, files: list[Path]):
        exts = {f.suffix.lower() for f in files}
        tools = [t for t in TOOLS.values() if exts and all(e in t.accepts for e in exts)]
        if not tools:
            self.toast.show_message("No tool takes these files", "err")
            return
        m = QMenu(self)
        m.addSection(f"{len(files)} file{'s' if len(files) != 1 else ''} - choose a tool")
        suite = getattr(self, "suite", None)
        readable = [f for f in files if f.suffix.lower() in (".pdf", ".txt", ".md", ".docx", ".epub", ".html")]
        if suite is not None and readable:
            a = m.addAction(T.icon("volume", T.ACCENT2, 18), "Read aloud  (Read & Listen)")
            a.triggered.connect(lambda _=False: suite.listen(readable))
            m.addSeparator()
        order = {c: i for i, c in enumerate(CATEGORIES)}
        for t in sorted(tools, key=lambda t: order.get(t.category, 99)):
            a = m.addAction(T.icon(t.icon, t.color, 18), t.name)
            a.triggered.connect(lambda _=False, tid=t.id: self.open_tool(tid, files))
        m.exec(QCursor.pos())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        from .widgets import collect_files
        allx = sorted({x for t in TOOLS.values() for x in t.accepts})
        fs = collect_files([u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()], allx)
        if fs:
            self.pick_tool_for(fs)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            p = self.toast.parentWidget()
            self.toast.move(p.width() - self.toast.width() - 24, p.height() - self.toast.height() - 70)
