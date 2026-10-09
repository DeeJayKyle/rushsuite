"""Workflows: build a chain of tools once, then run it on any files with one click."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)

from ..core import workflow as W
from ..core.registry import TOOLS
from . import theme as T
from .tool_page import FileList, ResultsCard, output_dir_for, remember, unlock_inputs
from .widgets import (Busy, DropZone, Page, ParamForm, button, card, collect_files, error_box, label, run_bg)


class WorkflowsPage(Page):
    def __init__(self, main=None):
        super().__init__("Workflows", "Chain tools together - e.g. Merge → Compress → Watermark → Protect - and run "
                                      "them on any files in one go.", max_width=1200)
        self.main = main
        self.flows = W.load()
        self.cur: dict | None = None
        self.step_i = -1
        self.form: ParamForm | None = None

        top = QHBoxLayout()
        top.setSpacing(16)
        # list
        left, lv = card()
        left.setFixedWidth(280)
        lv.addWidget(label("Your workflows", "h2"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        nb = button("New", "plus")
        nb.clicked.connect(self.new)
        db = button("", "layers", "ghost", "Duplicate")
        db.clicked.connect(self.duplicate)
        xb = button("", "trash", "ghost", "Delete")
        xb.clicked.connect(self.delete)
        row.addWidget(nb)
        row.addStretch(1)
        row.addWidget(db)
        row.addWidget(xb)
        lv.addLayout(row)
        top.addWidget(left)

        # editor
        right = QVBoxLayout()
        ed, ev = card()
        nrow = QHBoxLayout()
        nrow.addWidget(label("Name", "muted"))
        self.name = QLineEdit()
        self.name.textEdited.connect(self._rename)
        nrow.addWidget(self.name, 1)
        ev.addLayout(nrow)
        ev.addWidget(label("Steps (run top to bottom)", "h2"))
        self.steps = QListWidget()
        self.steps.setFixedHeight(170)
        self.steps.currentRowChanged.connect(self.select_step)
        ev.addWidget(self.steps)
        srow = QHBoxLayout()
        self.add_combo = QComboBox()
        for t in W.chainable():
            self.add_combo.addItem(T.icon(t.icon, t.color, 16), t.name, t.id)
        srow.addWidget(self.add_combo, 1)
        ab = button("Add step", "plus")
        ab.clicked.connect(self.add_step)
        srow.addWidget(ab)
        up = button("", "left", "ghost", "Move up")
        up.clicked.connect(lambda: self.move(-1))
        dn = button("", "right", "ghost", "Move down")
        dn.clicked.connect(lambda: self.move(1))
        rm = button("", "trash", "ghost", "Remove step")
        rm.clicked.connect(self.remove_step)
        for w in (up, dn, rm):
            srow.addWidget(w)
        ev.addLayout(srow)
        self.opt_title = label("", "h2")
        ev.addWidget(self.opt_title)
        self.opt_holder = QVBoxLayout()
        ev.addLayout(self.opt_holder)
        right.addWidget(ed)
        top.addLayout(right, 1)
        self.body.addLayout(top)

        # run
        run, rv = card()
        rv.addWidget(label("Run this workflow", "h2"))
        self.drop = DropZone("Drop files to process", "PDFs, images or Office files - depending on the first step",
                             "upload", folders=True, filter_="All files (*)", height=120)
        self.drop.dropped.connect(lambda items: self.files.add(collect_files(items, self._first_accepts())))
        rv.addWidget(self.drop)
        self.files = FileList([".pdf"])
        self.files.setMinimumHeight(170)
        rv.addWidget(self.files)
        rrow = QHBoxLayout()
        clr = button("Clear files", "x", "ghost")
        clr.clicked.connect(self.files.clear)
        rrow.addWidget(clr)
        rrow.addStretch(1)
        self.run_b = button("Run workflow", "workflow", "primary")
        self.run_b.clicked.connect(self.run)
        rrow.addWidget(self.run_b)
        rv.addLayout(rrow)
        self.busy = Busy()
        rv.addWidget(self.busy)
        self.body.addWidget(run)
        self.results = ResultsCard(main)
        self.body.addWidget(self.results)
        self.finish()
        self._fill_list()

    # ------------------------------------------------------------------ list
    def _fill_list(self, select: int = 0):
        self.list.blockSignals(True)
        self.list.clear()
        for f in self.flows:
            self.list.addItem(QListWidgetItem(T.icon("workflow", T.ACCENT, 18), f.get("name", "Workflow")))
        self.list.blockSignals(False)
        if self.flows:
            self.list.setCurrentRow(min(select, len(self.flows) - 1))
        else:
            self.select(-1)

    def _save(self):
        W.save_all(self.flows)

    def new(self):
        name, ok = QInputDialog.getText(self, "New workflow", "Name:", QLineEdit.Normal, "My workflow")
        if ok:
            self.flows.append({"name": name.strip() or "My workflow", "steps": []})
            self._save()
            self._fill_list(len(self.flows) - 1)

    def duplicate(self):
        if self.cur is not None:
            c = copy.deepcopy(self.cur)
            c["name"] += " (copy)"
            self.flows.append(c)
            self._save()
            self._fill_list(len(self.flows) - 1)

    def delete(self):
        r = self.list.currentRow()
        if 0 <= r < len(self.flows):
            del self.flows[r]
            self._save()
            self._fill_list(max(0, r - 1))

    def select(self, r):
        self.cur = self.flows[r] if 0 <= r < len(self.flows) else None
        self.name.setText(self.cur["name"] if self.cur else "")
        self._fill_steps()

    def _rename(self, text):
        if self.cur is not None:
            self.cur["name"] = text
            item = self.list.currentItem()
            if item is not None:
                item.setText(text)
            self._save()

    # ------------------------------------------------------------------ steps
    def _fill_steps(self, select: int = 0):
        self.steps.blockSignals(True)
        self.steps.clear()
        for k, st in enumerate((self.cur or {}).get("steps", [])):
            t = TOOLS.get(st["tool"])
            name = t.name if t else st["tool"]
            self.steps.addItem(QListWidgetItem(T.icon(t.icon if t else "x", t.color if t else T.DANGER, 18),
                                               f"{k + 1}.  {name}"))
        self.steps.blockSignals(False)
        n = self.steps.count()
        if n:
            self.steps.setCurrentRow(min(select, n - 1))
        else:
            self.select_step(-1)

    def select_step(self, r):
        self.step_i = r
        if self.form is not None:
            self.form.setParent(None)
            self.form.deleteLater()
            self.form = None
        steps = (self.cur or {}).get("steps", [])
        if not (0 <= r < len(steps)):
            self.opt_title.setText("")
            return
        st = steps[r]
        t = TOOLS.get(st["tool"])
        if t is None:
            self.opt_title.setText("Unknown tool")
            return
        self.opt_title.setText(f"{t.name} options" if t.params else f"{t.name} (no options)")
        self.form = ParamForm(t.params, st.get("params", {}))
        self.form.changed.connect(self._store)
        self.opt_holder.addWidget(self.form)
        self._store()

    def _store(self):
        steps = (self.cur or {}).get("steps", [])
        if self.form is not None and 0 <= self.step_i < len(steps):
            t = TOOLS.get(steps[self.step_i]["tool"])
            secret = {p.key for p in (t.params if t else []) if p.kind == "password"}
            # passwords are never written to disk - they're asked for when the workflow runs
            steps[self.step_i]["params"] = {k: v for k, v in self.form.values().items() if k not in secret}
            self._save()

    def add_step(self):
        if self.cur is None:
            self.new()
            if self.cur is None:
                return
        self.cur["steps"].append({"tool": self.add_combo.currentData(), "params": {}})
        self._save()
        self._fill_steps(len(self.cur["steps"]) - 1)

    def move(self, d):
        steps = (self.cur or {}).get("steps", [])
        i = self.step_i
        j = i + d
        if 0 <= i < len(steps) and 0 <= j < len(steps):
            steps[i], steps[j] = steps[j], steps[i]
            self._save()
            self._fill_steps(j)

    def remove_step(self):
        steps = (self.cur or {}).get("steps", [])
        if 0 <= self.step_i < len(steps):
            del steps[self.step_i]
            self._save()
            self._fill_steps(max(0, self.step_i - 1))

    # ------------------------------------------------------------------ run
    def _first_accepts(self) -> list[str]:
        steps = (self.cur or {}).get("steps", [])
        t = TOOLS.get(steps[0]["tool"]) if steps else None
        return t.accepts if t else [".pdf"]

    def set_files(self, files):
        self.files.add([Path(f) for f in files])

    def run(self):
        if self.cur is None or not self.cur.get("steps"):
            error_box(self, "Add at least one step to this workflow.")
            return
        miss = W.needs(self.cur)
        overrides = {}
        for k, why in miss:
            if "password" in why.lower():
                pw, ok = QInputDialog.getText(self, "Password", f"Step {k + 1}: {why}.\nPassword to use:",
                                              QLineEdit.Password)
                if not ok or not pw:
                    return
                overrides[k] = {"password": pw}
            else:
                error_box(self, why)
                return
        files = self.files.files()
        if not files:
            error_box(self, "Add the files to process first.")
            return
        files = unlock_inputs(self, files)
        if files is None:
            return
        self.run_b.setEnabled(False)
        self.results.hide()
        self.busy.start("Running workflow…")

        def ok(res):
            self.busy.done()
            self.run_b.setEnabled(True)
            res = [Path(r) for r in res]
            remember(res)
            self.results.show_results(res, f"Workflow '{self.cur['name']}' finished.")
            if self.main is not None:
                self.main.toast.show_message("Workflow finished")

        def fail(msg):
            self.busy.done()
            self.run_b.setEnabled(True)
            error_box(self, msg)
        run_bg(self, W.run, copy.deepcopy(self.cur), files, output_dir_for(self.files.files()),
               overrides=overrides, on_progress=self.busy.update_, on_done=ok, on_fail=fail)

