"""Desktop window, in Qt via PySide6.

Qt rather than Tkinter for three reasons that all show up on Windows: it is
crisp on scaled displays without any manual DPI arithmetic, it uses the native
widget metrics so the window does not look like a 1997 X11 app, and its item
views can hold a hundred and forty rows without the scroll jank Tk's Treeview
has at that size.

All the slow work runs on :class:`mbworkbook.jobs.Worker` and reports back
through a queue that a QTimer drains on the UI thread. That keeps the toolkit
out of the business logic - the same worker is unit-tested without a display -
and gives every long job a cancel point.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction, QFont, QKeySequence
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QSplitter,
        QTabWidget,
        QHeaderView,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised by the entry point
    raise SystemExit(
        "The desktop window needs PySide6. Install it with:\n"
        "    pip install PySide6\n"
        "Or use the command line instead:  mbworkbook --help"
    ) from exc

from . import __version__
from .jobs import Worker
from .models import Badge, CatalogEntry
from .paths import migrate_legacy_dirs, settings_path
from .render import WorkbookOptions
from .service import (
    FORMAT_LABELS,
    catalog_entries,
    fetch_badge,
    output_filename,
    snapshot,
    write_output,
)
from .snapshot import check_for_updates

POLL_MS = 60
FORMATS = ["md", "html", "pdf", "json", "card"]


class App(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker = Worker()
        self.catalog: list[CatalogEntry] = []
        self.preview_badge: Badge | None = None
        self.saved_page: Path | None = None

        self.setWindowTitle("Merit Badge Workbook")
        self.resize(1100, 720)
        self.setMinimumSize(900, 580)

        self._build_ui()
        self._build_menu()
        self._load_settings()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain)
        self.timer.start(POLL_MS)

        for old, new in migrate_legacy_dirs():
            self.log(f"Moved {old} -> {new}")

        self.load_catalog()

    # ------------------------------------------------------------------ build

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._badge_pane())
        splitter.addWidget(self._right_pane())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 770])

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.addWidget(splitter, 1)
        outer.addLayout(self._action_bar())
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.status = self.statusBar()
        self.status.addPermanentWidget(self.progress)
        self.status.showMessage("Starting…")

    def _badge_pane(self) -> QWidget:
        pane = QWidget()
        box = QVBoxLayout(pane)
        box.setContentsMargins(0, 0, 8, 0)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter badges…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        box.addWidget(self.filter_edit)

        self.eagle_only = QCheckBox("Eagle-required only")
        self.eagle_only.toggled.connect(self._apply_filter)
        box.addWidget(self.eagle_only)

        self.badge_list = QListWidget()
        self.badge_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.badge_list.setAlternatingRowColors(True)
        self.badge_list.itemSelectionChanged.connect(self._sync_enabled)
        self.badge_list.itemDoubleClicked.connect(lambda _: self.preview())
        box.addWidget(self.badge_list, 1)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: palette(placeholderText);")
        box.addWidget(self.count_label)
        return pane

    def _right_pane(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._options_tab(), "Options")
        self.tabs.addTab(self._preview_tab(), "Preview")
        self.tabs.addTab(self._log_tab(), "Log")
        return self.tabs

    def _options_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        out_box = QGroupBox("Output")
        form = QFormLayout(out_box)
        self.format_combo = QComboBox()
        for key in FORMATS:
            self.format_combo.addItem(FORMAT_LABELS[key], key)
        self.format_combo.currentIndexChanged.connect(self._sync_enabled)
        form.addRow("Format", self.format_combo)

        self.style_combo = QComboBox()
        self.style_combo.addItem("Checklist — compact", "checklist")
        self.style_combo.addItem("Workbook — ruled writing space", "workbook")
        self.style_combo.currentIndexChanged.connect(self._sync_enabled)
        form.addRow("Style", self.style_combo)

        self.note_lines = QSpinBox()
        self.note_lines.setRange(1, 20)
        self.note_lines.setValue(4)
        form.addRow("Ruled lines", self.note_lines)

        self.show_signoff = QCheckBox("Date and counselor-initials columns")
        self.show_signoff.setChecked(True)
        form.addRow("", self.show_signoff)
        self.include_notes = QCheckBox("Keep “Resources:” links from the page")
        self.include_notes.setChecked(True)
        form.addRow("", self.include_notes)
        outer.addWidget(out_box)

        who_box = QGroupBox("Pre-fill")
        who = QFormLayout(who_box)
        self.scout_edit = QLineEdit()
        self.counselor_edit = QLineEdit()
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("Troop 379")
        who.addRow("Scout", self.scout_edit)
        who.addRow("Counselor", self.counselor_edit)
        who.addRow("Unit", self.unit_edit)
        outer.addWidget(who_box)

        dest_box = QGroupBox("Destination")
        dest = QVBoxLayout(dest_box)
        row = QHBoxLayout()
        self.outdir_edit = QLineEdit(str(Path.home() / "Documents"))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_outdir)
        row.addWidget(self.outdir_edit, 1)
        row.addWidget(browse)
        dest.addLayout(row)

        self.refresh_check = QCheckBox(
            "Re-fetch from scouting.org instead of using the built-in copy")
        self.refresh_check.toggled.connect(self._sync_enabled)
        dest.addWidget(self.refresh_check)
        self.combine_cards = QCheckBox(
            "Put every blue card in one PDF")
        self.combine_cards.setChecked(True)
        dest.addWidget(self.combine_cards)

        card_row = QHBoxLayout()
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText(
            "Blue card template (optional) — a council's fillable PDF")
        self.template_edit.textChanged.connect(self._sync_enabled)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self.choose_template)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.template_edit.clear())
        card_row.addWidget(self.template_edit, 1)
        card_row.addWidget(pick)
        card_row.addWidget(clear)
        dest.addLayout(card_row)
        outer.addWidget(dest_box)

        self.card_hint = QLabel("")
        self.card_hint.setWordWrap(True)
        self.card_hint.setStyleSheet("color: palette(placeholderText); font-size: 11px;")
        outer.addWidget(self.card_hint)

        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet("color: palette(placeholderText); font-size: 11px;")
        outer.addWidget(self.source_label)
        outer.addStretch(1)
        return page

    def _preview_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        self.preview_title = QLabel("Pick a badge and press Preview.")
        f = QFont()
        f.setBold(True)
        self.preview_title.setFont(f)
        box.addWidget(self.preview_title)

        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["#", "Requirement"])
        # Markers must never be elided - "(b)" reading as "(..." is worse than
        # a wider column - so let the header size itself to the deepest marker.
        self.preview_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.preview_tree.header().setStretchLastSection(True)
        self.preview_tree.setAlternatingRowColors(True)
        self.preview_tree.setWordWrap(True)
        box.addWidget(self.preview_tree, 1)
        return page

    def _log_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFont(QFont("Consolas" if sys.platform == "win32" else "Monospace", 9))
        box.addWidget(self.log_view, 1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.log_view.clear)
        box.addWidget(clear, 0, Qt.AlignRight)
        return page

    def _action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.btn_preview = QPushButton("Preview")
        self.btn_preview.clicked.connect(self.preview)
        self.btn_generate = QPushButton("Generate")
        self.btn_generate.setDefault(True)
        self.btn_generate.clicked.connect(self.generate)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_open = QPushButton("Open folder")
        self.btn_open.clicked.connect(self.open_output_folder)

        row.addWidget(self.btn_open)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_generate)
        return row

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        act_open = QAction("Open saved badge page…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self.open_saved_page)
        file_menu.addAction(act_open)
        act_folder = QAction("Open output folder", self)
        act_folder.triggered.connect(self.open_output_folder)
        file_menu.addAction(act_folder)
        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        data_menu = bar.addMenu("&Requirements")
        act_check = QAction("Check for updates…", self)
        act_check.triggered.connect(self.check_updates)
        data_menu.addAction(act_check)
        act_reload = QAction("Reload badge list from scouting.org", self)
        act_reload.triggered.connect(lambda: self.load_catalog(refresh=True))
        data_menu.addAction(act_reload)

        help_menu = bar.addMenu("&Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    # ------------------------------------------------------------- state sync

    def options(self) -> WorkbookOptions:
        return WorkbookOptions(
            scout=self.scout_edit.text().strip(),
            counselor=self.counselor_edit.text().strip(),
            unit=self.unit_edit.text().strip(),
            style=self.style_combo.currentData(),
            note_lines=self.note_lines.value(),
            show_signoff=self.show_signoff.isChecked(),
            include_notes=self.include_notes.isChecked(),
            card_template=self.template_edit.text().strip(),
        )

    @property
    def fmt(self) -> str:
        return self.format_combo.currentData()

    def selected(self) -> list[CatalogEntry]:
        return [i.data(Qt.UserRole) for i in self.badge_list.selectedItems()]

    def _sync_enabled(self) -> None:
        busy = self.worker.busy
        is_card = self.fmt == "card"
        workbook = self.style_combo.currentData() == "workbook"

        self.btn_cancel.setEnabled(busy)
        self.btn_generate.setEnabled(not busy)
        self.btn_preview.setEnabled(not busy)
        self.note_lines.setEnabled(workbook and not is_card)
        self.style_combo.setEnabled(not is_card)
        self.show_signoff.setEnabled(not is_card)
        self.include_notes.setEnabled(not is_card)
        self.combine_cards.setEnabled(is_card)
        self.template_edit.setEnabled(is_card)

        if is_card:
            tpl = self.template_edit.text().strip()
            self.card_hint.setText(
                f"Filling {Path(tpl).name}." if tpl else
                "No template set — drawing our own three-part card. Point this "
                "at your council's fillable blue card PDF to use the real form.")
        self.card_hint.setVisible(is_card)

        snap = snapshot()
        if self.refresh_check.isChecked():
            self.source_label.setText(
                "Requirements will be fetched live from scouting.org "
                "(about one second per badge)."
            )
        elif snap:
            self.source_label.setText(
                f"Using the requirements shipped with this app, built "
                f"{snap.built_date} ({len(snap.badges)} badges). "
                f"Requirements → Check for updates compares them against the site."
            )
        else:
            self.source_label.setText(
                "No built-in requirements found; everything will be fetched live."
            )

    # ---------------------------------------------------------------- catalog

    def load_catalog(self, *, refresh: bool = False) -> None:
        self.status.showMessage("Loading badge list…")
        self._busy(True, indeterminate=True)

        def job() -> None:
            entries = catalog_entries(refresh=refresh, offline=not refresh)
            self.worker.send("catalog", entries)

        if not self.worker.start(job):
            self.status.showMessage("Busy — wait for the current job.")
        self._sync_enabled()

    def _apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        eagle = self.eagle_only.isChecked()
        shown = 0
        for row in range(self.badge_list.count()):
            item = self.badge_list.item(row)
            entry: CatalogEntry = item.data(Qt.UserRole)
            ok = (not needle or needle in entry.name.lower() or needle in entry.slug)
            if eagle and not entry.eagle_required:
                ok = False
            item.setHidden(not ok)
            shown += ok
        self.count_label.setText(f"{shown} of {self.badge_list.count()} badges")

    def _fill_catalog(self, entries: list[CatalogEntry]) -> None:
        self.catalog = entries
        self.badge_list.clear()
        for entry in entries:
            label = entry.name + ("  ★" if entry.eagle_required else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            if entry.eagle_required:
                item.setToolTip("Eagle-required")
            self.badge_list.addItem(item)
        self._apply_filter()
        self.status.showMessage(f"{len(entries)} badges available.", 4000)

    # ---------------------------------------------------------------- actions

    def preview(self) -> None:
        chosen = self.selected()
        if not chosen and not self.saved_page:
            QMessageBox.information(self, "Nothing selected",
                                    "Pick a badge from the list first.")
            return
        entry = chosen[0] if chosen else None
        refresh = self.refresh_check.isChecked()
        page = self.saved_page if entry is None else None

        self.status.showMessage(f"Loading {entry.name if entry else page.name}…")
        self._busy(True, indeterminate=True)

        def job() -> None:
            badge = fetch_badge(entry, refresh=refresh, offline=not refresh,
                                html_file=page)
            self.worker.send("preview", badge)

        if self.worker.start(job):
            self.tabs.setCurrentIndex(1)
        self._sync_enabled()

    def generate(self) -> None:
        chosen = self.selected()
        if not chosen and not self.saved_page:
            QMessageBox.information(self, "Nothing selected",
                                    "Pick one or more badges from the list first.")
            return

        outdir = Path(self.outdir_edit.text()).expanduser()
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot write there", str(exc))
            return

        options = self.options()
        fmt = self.fmt
        refresh = self.refresh_check.isChecked()
        entries: list = chosen or [None]
        page = self.saved_page if not chosen else None
        combine = fmt == "card" and self.combine_cards.isChecked() and len(entries) > 1

        self._busy(True, maximum=len(entries))
        self.status.showMessage(f"Generating {len(entries)} file(s)…")
        self.tabs.setCurrentIndex(2)
        self.log(f"--- {len(entries)} badge(s) as {FORMAT_LABELS[fmt]} into {outdir}")

        def job() -> None:
            collected: list[Badge] = []
            written = 0
            for index, entry in enumerate(entries, 1):
                self.worker.raise_if_cancelled()
                label = entry.name if entry else page.name
                try:
                    badge = fetch_badge(entry, refresh=refresh,
                                        offline=not refresh, html_file=page)
                    if not badge.requirements:
                        self.worker.send("log", (
                            f"! {label}: no requirements found. Try File > Open "
                            f"saved badge page, or Requirements > Check for updates."))
                        continue
                    if combine:
                        collected.append(badge)
                    else:
                        path = outdir / output_filename(badge, options.style, fmt)
                        write_output(badge, options, fmt, path)
                        written += 1
                        self.worker.send("log", (
                            f"  {badge.name}: {badge.total_requirements()} items "
                            f"-> {path.name}"))
                except Exception as exc:  # noqa: BLE001 - one bad badge, not all
                    self.worker.send("log", f"! {label}: {type(exc).__name__}: {exc}")
                self.worker.send("progress", index)

            if combine and collected:
                from .service import write_cards

                path = outdir / "merit-badge-cards.pdf"
                write_cards(collected, options, path)
                written = len(collected)
                self.worker.send("log", f"  {written} cards -> {path.name}")

            self.worker.send("log", f"Done. {written} of {len(entries)} written.")

        if not self.worker.start(job):
            self.status.showMessage("Busy — wait for the current job.")
        self._sync_enabled()

    def check_updates(self) -> None:
        snap = snapshot()
        if not snap:
            QMessageBox.information(
                self, "Nothing to compare",
                "This build has no bundled requirements, so everything is "
                "already fetched live.")
            return

        ok = QMessageBox.question(
            self, "Check for updates",
            f"This re-fetches all {len(snap.badges)} badges from scouting.org at "
            f"one per second — about {len(snap.badges) // 60 + 1} minutes — and "
            f"reports what has changed since {snap.built_date}.\n\nYou can cancel "
            f"at any point.\n\nStart now?",
        )
        if ok != QMessageBox.Yes:
            return

        self._busy(True, maximum=len(snap.badges) or 1)
        self.status.showMessage("Checking scouting.org for changes…")
        self.tabs.setCurrentIndex(2)
        self.log(f"--- Checking {len(snap.badges)} badges against the site")

        def job() -> None:
            entries = catalog_entries(refresh=True, offline=False)
            report = check_for_updates(
                snap, entries,
                fetch=lambda e: fetch_badge(e, refresh=True, offline=False),
                on_progress=lambda i, e: self.worker.send("progress", i),
                should_cancel=lambda: self.worker.cancelled,
            )
            self.worker.send("report", report)

        if not self.worker.start(job):
            self.status.showMessage("Busy — wait for the current job.")
        self._sync_enabled()

    def cancel(self) -> None:
        if self.worker.busy:
            self.worker.cancel()
            self.status.showMessage("Stopping after the current badge…")
            self.btn_cancel.setEnabled(False)

    def open_saved_page(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a saved badge page", str(Path.home()),
            "HTML pages (*.html *.htm);;All files (*)")
        if not path:
            return
        self.saved_page = Path(path)
        self.badge_list.clearSelection()
        self.log(f"Using saved page {self.saved_page}")
        self.status.showMessage(f"Saved page: {self.saved_page.name}")
        self.preview()

    def choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a fillable blue card PDF", str(Path.home()),
            "PDF forms (*.pdf);;All files (*)")
        if not path:
            return
        from .render.cardform import looks_like_template

        if not looks_like_template(path):
            QMessageBox.warning(
                self, "Not a blue card template",
                f"{Path(path).name} does not carry the blue card's form "
                f"fields.\n\n"
                f"You want the fillable 'Application for Merit Badge' PDF that "
                f"councils publish, not a flattened scan.")
            return
        self.template_edit.setText(path)

    def choose_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Where should the files go?", self.outdir_edit.text())
        if path:
            self.outdir_edit.setText(path)

    def open_output_folder(self) -> None:
        path = Path(self.outdir_edit.text()).expanduser()
        if not path.is_dir():
            QMessageBox.information(self, "Not there yet",
                                    f"{path} does not exist. Generate something first.")
            return
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - a user-chosen directory
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _about(self) -> None:
        snap = snapshot()
        built = (f"Bundled requirements: {len(snap.badges)} badges, built "
                 f"{snap.built_date}." if snap else "No bundled requirements.")
        QMessageBox.about(
            self, "Merit Badge Workbook",
            f"<b>Merit Badge Workbook {__version__}</b>"
            f"<p>Printable requirement checklists, workbooks and application "
            f"cards for Scouting America merit badges.</p>"
            f"<p>{built}</p>"
            f"<p style='color:#666'>Requirement text belongs to Scouting America. "
            f"These sheets are a note-taking aid; the official requirements are "
            f"the ones at scouting.org and in the current pamphlet.</p>")

    # ------------------------------------------------------------- UI plumbing

    def log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _busy(self, busy: bool, *, maximum: int = 0, indeterminate: bool = False) -> None:
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0 if indeterminate else maximum)
            self.progress.setValue(0)
        self._sync_enabled()

    def _drain(self) -> None:
        for msg in self.worker.drain():
            self._handle(msg)

    def _handle(self, msg) -> None:
        if msg.kind == "catalog":
            self._fill_catalog(msg.payload)
        elif msg.kind == "preview":
            self._show_preview(msg.payload)
        elif msg.kind == "log":
            self.log(str(msg.payload))
        elif msg.kind == "progress":
            self.progress.setValue(int(msg.payload))
        elif msg.kind == "status":
            self.status.showMessage(str(msg.payload))
        elif msg.kind == "report":
            self._show_report(msg.payload)
        elif msg.kind == "cancelled":
            self.log("Cancelled.")
            self.status.showMessage("Cancelled.", 5000)
        elif msg.kind == "error":
            self.log(f"! {msg.payload}")
            self.status.showMessage(str(msg.payload), 8000)
        elif msg.kind == "done":
            self._busy(False)
            if not self.status.currentMessage().startswith(("Cancel", "Stopping")):
                self.status.showMessage("Ready.", 3000)

    def _show_preview(self, badge: Badge) -> None:
        self.preview_badge = badge
        self.preview_tree.clear()
        title = f"{badge.name} — {badge.total_requirements()} items"
        if badge.eagle_required:
            title += " · Eagle-required"
        if badge.source_retrieved:
            title += f" · retrieved {badge.source_retrieved[:10]}"
        self.preview_title.setText(title)

        def add(req, parent) -> None:
            node = QTreeWidgetItem(parent, [req.label, req.text])
            for note in req.notes:
                QTreeWidgetItem(node, ["", note])
            for child in req.children:
                add(child, node)

        for req in badge.requirements:
            add(req, self.preview_tree)
        self.preview_tree.expandToDepth(1)
        if not badge.requirements:
            self.preview_title.setText(
                f"{badge.name} — no requirements parsed. The page may have "
                f"changed; try Requirements > Check for updates.")

    def _show_report(self, report) -> None:
        self.log(report.summary())
        for slug in report.changed:
            self.log(f"  changed: {slug}")
        for slug in report.added:
            self.log(f"  new on the site: {slug}")
        for slug in report.removed:
            self.log(f"  no longer listed: {slug}")
        for line in report.failed:
            self.log(f"  ! {line}")

        if report.cancelled:
            return
        if report.any_changes:
            QMessageBox.warning(
                self, "Requirements have changed",
                f"{report.summary()}\n\nThe built-in copy is out of date for "
                f"those badges. Tick “Re-fetch from scouting.org” before "
                f"generating them, and see the Log tab for the list.")
        else:
            QMessageBox.information(self, "Up to date", report.summary())

    # --------------------------------------------------------------- settings

    def _setting_widgets(self) -> dict:
        return {
            "format": (self.format_combo, "data"),
            "style": (self.style_combo, "data"),
            "note_lines": (self.note_lines, "int"),
            "show_signoff": (self.show_signoff, "bool"),
            "include_notes": (self.include_notes, "bool"),
            "combine_cards": (self.combine_cards, "bool"),
            "scout": (self.scout_edit, "text"),
            "counselor": (self.counselor_edit, "text"),
            "unit": (self.unit_edit, "text"),
            "outdir": (self.outdir_edit, "text"),
            "card_template": (self.template_edit, "text"),
        }

    def _load_settings(self) -> None:
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._sync_enabled()
            return

        for key, (widget, kind) in self._setting_widgets().items():
            if key not in data:
                continue
            value = data[key]
            try:
                if kind == "data":
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                elif kind == "int":
                    widget.setValue(int(value))
                elif kind == "bool":
                    widget.setChecked(bool(value))
                else:
                    widget.setText(str(value))
            except (TypeError, ValueError):
                continue  # A corrupt entry should not stop the window opening.
        self._sync_enabled()

    def save_settings(self) -> None:
        data = {}
        for key, (widget, kind) in self._setting_widgets().items():
            if kind == "data":
                data[key] = widget.currentData()
            elif kind == "int":
                data[key] = widget.value()
            elif kind == "bool":
                data[key] = widget.isChecked()
            else:
                data[key] = widget.text()
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # Losing preferences is not worth blocking a quit over.

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.worker.busy:
            self.worker.cancel()
        self.save_settings()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Merit Badge Workbook")
    app.setOrganizationName("Merit Badge Workbook")
    window = App()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
