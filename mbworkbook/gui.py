"""Tkinter desktop front end.

Launch with ``mbworkbook-gui``, ``python -m mbworkbook --gui``, or
``python -m mbworkbook.gui``.

Tkinter ships with Python on Windows and macOS. On Debian/Ubuntu it is a
separate package: ``sudo apt install python3-tk``.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The GUI needs tkinter, which is not installed.\n"
        "  Debian/Ubuntu:  sudo apt install python3-tk\n"
        "  Fedora:         sudo dnf install python3-tkinter\n"
        "  macOS/Windows:  reinstall Python from python.org\n"
        "The command line interface works without it: mbworkbook --help"
    ) from exc

from .catalog import load_catalog
from .fetch import FetchError
from .models import Badge, CatalogEntry
from .render import WorkbookOptions
from .service import FORMAT_LABELS, fetch_badge, output_filename, write_output

SETTINGS_PATH = Path(
    os.environ.get("MBW_CONFIG_DIR", Path.home() / ".config" / "merit-badge-workbook")
) / "gui.json"

PAD = 8


# --------------------------------------------------------------------------
# Worker plumbing
# --------------------------------------------------------------------------


@dataclass
class Message:
    """One event from the worker thread back to the UI."""

    kind: str  # "catalog" | "preview" | "log" | "progress" | "done" | "error"
    payload: object = None


class Worker:
    """Runs one background job at a time and reports through a queue."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[Message]" = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def send(self, kind: str, payload: object = None) -> None:
        self.queue.put(Message(kind, payload))

    def start(self, fn, *args, **kwargs) -> bool:
        if self.busy:
            return False

        def run() -> None:
            try:
                fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI
                self.send("error", f"{type(exc).__name__}: {exc}")
                self.send("log", traceback.format_exc())
            finally:
                self.send("done", None)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=PAD)
        self.master = master
        self.worker = Worker()
        self.catalog: list[CatalogEntry] = []
        self.shown: list[CatalogEntry] = []
        self.preview_badge: Badge | None = None

        master.title("Merit Badge Workbook")
        master.geometry("1020x680")
        master.minsize(860, 560)
        self.pack(fill="both", expand=True)

        self._build_vars()
        self._build_menu()
        self._build_layout()
        self._load_settings()

        self.after(80, self._drain)
        self.refresh_catalog()

    # ---------------------------------------------------------------- state

    def _build_vars(self) -> None:
        self.var_search = tk.StringVar()
        self.var_eagle_only = tk.BooleanVar(value=False)
        self.var_format = tk.StringVar(value="pdf")
        self.var_style = tk.StringVar(value="checklist")
        self.var_note_lines = tk.IntVar(value=4)
        self.var_signoff = tk.BooleanVar(value=True)
        self.var_resources = tk.BooleanVar(value=True)
        self.var_scout = tk.StringVar()
        self.var_counselor = tk.StringVar()
        self.var_unit = tk.StringVar()
        self.var_outdir = tk.StringVar(value=str(Path.cwd()))
        self.var_refresh = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Starting…")

        self.var_search.trace_add("write", lambda *_: self._filter())
        self.var_eagle_only.trace_add("write", lambda *_: self._filter())
        self.var_style.trace_add("write", lambda *_: self._sync_enabled())

    def options(self) -> WorkbookOptions:
        return WorkbookOptions(
            scout=self.var_scout.get().strip(),
            counselor=self.var_counselor.get().strip(),
            unit=self.var_unit.get().strip(),
            style=self.var_style.get(),
            note_lines=max(0, self.var_note_lines.get()),
            show_signoff=self.var_signoff.get(),
            include_notes=self.var_resources.get(),
        )

    # --------------------------------------------------------------- layout

    def _build_menu(self) -> None:
        menu = tk.Menu(self.master)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Open saved badge page…",
                              command=self.open_saved_page)
        file_menu.add_command(label="Reload badge list from scouting.org",
                              command=lambda: self.refresh_catalog(force=True))
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.master.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.master.config(menu=menu)

    def _build_layout(self) -> None:
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        panes.add(self._badge_pane(panes), weight=2)
        panes.add(self._right_pane(panes), weight=3)
        self._status_bar().pack(fill="x", pady=(PAD, 0))
        self._sync_enabled()

    def _badge_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=(0, 0, PAD, 0))

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Filter").pack(side="left")
        ttk.Checkbutton(top, text="Eagle only",
                        variable=self.var_eagle_only).pack(side="right")
        entry = ttk.Entry(top, textvariable=self.var_search)
        entry.pack(side="left", fill="x", expand=True, padx=(6, 10))
        entry.bind("<Escape>", lambda _e: self.var_search.set(""))

        self.tree = ttk.Treeview(
            frame, columns=("eagle",), selectmode="extended", height=20,
        )
        self.tree.heading("#0", text="Merit badge")
        self.tree.heading("eagle", text="Eagle")
        self.tree.column("#0", width=250, anchor="w")
        self.tree.column("eagle", width=52, anchor="center", stretch=False)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(6, 0))
        scroll.pack(side="left", fill="y", pady=(6, 0))

        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_enabled())
        self.tree.bind("<Double-1>", lambda _e: self.preview())
        return frame

    def _right_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        book = ttk.Notebook(frame)
        book.pack(fill="both", expand=True)
        book.add(self._options_tab(book), text="Options")
        book.add(self._preview_tab(book), text="Preview")
        book.add(self._log_tab(book), text="Log")
        self.book = book

        actions = ttk.Frame(frame, padding=(0, PAD, 0, 0))
        actions.pack(fill="x")
        self.btn_preview = ttk.Button(actions, text="Preview requirements",
                                      command=self.preview)
        self.btn_preview.pack(side="left")
        self.btn_generate = ttk.Button(actions, text="Generate", command=self.generate)
        self.btn_generate.pack(side="right")
        self.btn_open = ttk.Button(actions, text="Open output folder",
                                   command=self.open_output_folder)
        self.btn_open.pack(side="right", padx=(0, 6))
        return frame

    def _options_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        tab.columnconfigure(1, weight=1)
        row = 0

        def section(title: str) -> None:
            nonlocal row
            pady = (0 if row == 0 else 12, 4)
            ttk.Label(tab, text=title, font=("TkDefaultFont", 9, "bold")).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=pady)
            row += 1

        def field(label: str, widget: tk.Widget, stretch: bool = True) -> None:
            nonlocal row
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=2)
            widget.grid(row=row, column=1, columnspan=2, pady=2,
                        sticky="ew" if stretch else "w")
            row += 1

        section("Output")
        fmt = ttk.Combobox(tab, state="readonly",
                           values=[FORMAT_LABELS[k] for k in FORMAT_LABELS])
        fmt.set(FORMAT_LABELS[self.var_format.get()])
        fmt.bind("<<ComboboxSelected>>", lambda _e: self.var_format.set(
            next(k for k, v in FORMAT_LABELS.items() if v == fmt.get())))
        field("Format", fmt)

        style = ttk.Frame(tab)
        ttk.Radiobutton(style, text="Checklist", value="checklist",
                        variable=self.var_style).pack(side="left")
        ttk.Radiobutton(style, text="Workbook (writing space)", value="workbook",
                        variable=self.var_style).pack(side="left", padx=(12, 0))
        field("Style", style, stretch=False)

        lines = ttk.Frame(tab)
        self.spin_lines = ttk.Spinbox(lines, from_=0, to=20, width=5,
                                      textvariable=self.var_note_lines)
        self.spin_lines.pack(side="left")
        ttk.Label(lines, text="per requirement, in workbook style",
                  foreground="#5b6b7c").pack(side="left", padx=(8, 0))
        field("Ruled lines", lines, stretch=False)

        checks = ttk.Frame(tab)
        ttk.Checkbutton(checks, text="Date / initials columns",
                        variable=self.var_signoff).pack(side="left")
        ttk.Checkbutton(checks, text="Keep resource links",
                        variable=self.var_resources).pack(side="left", padx=(12, 0))
        field("Include", checks, stretch=False)

        outdir = ttk.Frame(tab)
        ttk.Entry(outdir, textvariable=self.var_outdir).pack(
            side="left", fill="x", expand=True)
        ttk.Button(outdir, text="Browse…", width=9,
                   command=self.choose_outdir).pack(side="left", padx=(6, 0))
        field("Save to", outdir)

        section("Pre-filled on every sheet")
        field("Scout", ttk.Entry(tab, textvariable=self.var_scout))
        field("Counselor", ttk.Entry(tab, textvariable=self.var_counselor))
        field("Unit", ttk.Entry(tab, textvariable=self.var_unit))

        section("Fetching")
        ttk.Checkbutton(
            tab, text="Ignore the local cache and re-fetch from scouting.org",
            variable=self.var_refresh,
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(
            tab, foreground="#5b6b7c", wraplength=430, justify="left",
            text="Pages are cached for a week. Requirements do change, so "
                 "re-fetch before starting a new class. The date each sheet "
                 "was retrieved is printed on it.",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 0))
        return tab

    def _preview_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        self.preview_label = ttk.Label(
            tab, foreground="#5b6b7c",
            text="Select a badge and choose Preview to check the parsed "
                 "requirements before printing.")
        self.preview_label.pack(anchor="w", pady=(0, 6))

        # Treeview cannot wrap, so long requirements are clipped in the row.
        # The full text of whatever is selected goes in the detail label below.
        self.preview_detail = ttk.Label(
            tab, wraplength=520, justify="left", anchor="w", relief="groove",
            padding=6, text="")

        holder = ttk.Frame(tab)
        self.preview_tree = ttk.Treeview(holder, columns=("text",), height=15)
        self.preview_tree.heading("#0", text="Req.")
        self.preview_tree.heading("text", text="Requirement")
        self.preview_tree.column("#0", width=110, stretch=False)
        self.preview_tree.column("text", width=460)
        scroll = ttk.Scrollbar(holder, orient="vertical",
                               command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=scroll.set)
        self.preview_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        holder.pack(fill="both", expand=True)

        self.preview_detail.pack(fill="x", pady=(PAD, 0))
        self.preview_tree.bind("<<TreeviewSelect>>", self._show_detail)
        return tab

    def _show_detail(self, _event=None) -> None:
        selection = self.preview_tree.selection()
        if not selection:
            self.preview_detail.configure(text="")
            return
        item = self.preview_tree.item(selection[0])
        marker = item["text"]
        text = (item["values"] or [""])[0]
        self.preview_detail.configure(
            text=f"{marker} {text}".strip() or "(no text)")

    def _log_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        self.log_text = tk.Text(tab, height=10, wrap="word", state="disabled",
                                font=("TkFixedFont", 9))
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        return tab

    def _status_bar(self) -> ttk.Frame:
        bar = ttk.Frame(self)
        self.progress = ttk.Progressbar(bar, mode="determinate", length=150)
        self.progress.pack(side="right")
        ttk.Label(bar, textvariable=self.var_status, foreground="#5b6b7c").pack(
            side="left", fill="x", expand=True)
        return bar

    # ------------------------------------------------------------- catalog

    def refresh_catalog(self, *, force: bool = False) -> None:
        if self.worker.busy:
            return
        self.var_status.set("Loading badge list from scouting.org…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def job() -> None:
            entries = load_catalog(force_refresh=force)
            self.worker.send("catalog", entries)

        self.worker.start(job)

    def _filter(self) -> None:
        needle = self.var_search.get().strip().lower()
        eagle_only = self.var_eagle_only.get()
        self.shown = [
            e for e in self.catalog
            if (not eagle_only or e.eagle_required)
            and (not needle or needle in e.name.lower() or needle in e.slug)
        ]
        self.tree.delete(*self.tree.get_children())
        for entry in self.shown:
            self.tree.insert("", "end", iid=entry.slug, text=entry.name,
                             values=("★" if entry.eagle_required else "",))
        self._sync_enabled()

    def selected(self) -> list[CatalogEntry]:
        by_slug = {e.slug: e for e in self.catalog}
        return [by_slug[s] for s in self.tree.selection() if s in by_slug]

    # ------------------------------------------------------------- actions

    def preview(self) -> None:
        chosen = self.selected()
        if not chosen:
            return
        entry = chosen[0]
        self.book.select(1)
        self.var_status.set(f"Fetching {entry.name}…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def job() -> None:
            badge = fetch_badge(entry, refresh=self.var_refresh.get())
            self.worker.send("preview", badge)

        if not self.worker.start(job):
            self.var_status.set("Busy — wait for the current job to finish.")

    def generate(self) -> None:
        chosen = self.selected()
        if not chosen and not self.preview_badge:
            messagebox.showinfo("Nothing selected",
                                "Pick one or more badges from the list first.")
            return

        outdir = Path(self.var_outdir.get()).expanduser()
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Cannot write there", str(exc))
            return

        options = self.options()
        fmt = self.var_format.get()
        refresh = self.var_refresh.get()
        entries = chosen or [None]
        saved_page = None if chosen else self.preview_badge

        self.progress.configure(mode="determinate", maximum=len(entries), value=0)
        self.var_status.set(f"Generating {len(entries)} file(s)…")

        def job() -> None:
            written = 0
            for index, entry in enumerate(entries, 1):
                label = entry.name if entry else saved_page.name
                try:
                    badge = saved_page if entry is None else fetch_badge(
                        entry, refresh=refresh)
                    if not badge.requirements:
                        self.worker.send("log", (
                            f"! {label}: no requirements found. The page layout "
                            f"may have changed, or the requirements are loaded by "
                            f"JavaScript. Save the page in a browser and use "
                            f"File > Open saved badge page."))
                        continue
                    path = outdir / output_filename(badge, options.style, fmt)
                    write_output(badge, options, fmt, path)
                    written += 1
                    self.worker.send("log", (
                        f"  {badge.name}: {badge.total_requirements()} items "
                        f"-> {path.name}"))
                except FetchError as exc:
                    self.worker.send("log", f"! {label}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    self.worker.send("log", f"! {label}: {type(exc).__name__}: {exc}")
                self.worker.send("progress", index)
            self.worker.send("log", f"Done. {written} of {len(entries)} written "
                                    f"to {outdir}")

        if not self.worker.start(job):
            self.var_status.set("Busy — wait for the current job to finish.")
            return
        self.book.select(2)

    def open_saved_page(self) -> None:
        path = filedialog.askopenfilename(
            title="Open a saved merit badge page",
            filetypes=[("HTML pages", "*.html *.htm"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            badge = fetch_badge(None, html_file=path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not parse that page", str(exc))
            return
        self.tree.selection_remove(*self.tree.selection())
        self._show_preview(badge)

    def choose_outdir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.var_outdir.get() or ".")
        if path:
            self.var_outdir.set(path)

    def open_output_folder(self) -> None:
        path = Path(self.var_outdir.get()).expanduser()
        if not path.exists():
            messagebox.showinfo("Not there yet", f"{path} does not exist.")
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif os.name == "nt":
                os.startfile(str(path))  # noqa: S606 - platform idiom
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not open folder", str(exc))

    def _about(self) -> None:
        messagebox.showinfo(
            "Merit Badge Workbook",
            "Builds requirement checklists and workbooks from the official "
            "badge pages at scouting.org.\n\n"
            "The generated sheets are a note-taking aid. The official, current "
            "requirements are the ones published at scouting.org and in the "
            "merit badge pamphlet.",
        )

    # ------------------------------------------------------------- plumbing

    def _show_preview(self, badge: Badge) -> None:
        self.preview_badge = badge
        self.preview_tree.delete(*self.preview_tree.get_children())

        def add(req, parent="") -> None:
            node = self.preview_tree.insert(
                parent, "end", text=req.label, values=(req.text,), open=True)
            for note in req.notes:
                self.preview_tree.insert(node, "end", text="", values=(note,))
            for child in req.children:
                add(child, node)

        for req in badge.requirements:
            add(req)
        self.preview_detail.configure(text="")

        if badge.requirements:
            self.preview_label.configure(
                foreground="#16202b",
                text=f"{badge.name} — {len(badge.requirements)} top-level, "
                     f"{badge.total_requirements()} items total. "
                     f"Retrieved {badge.source_retrieved[:10]}.")
        else:
            self.preview_label.configure(
                foreground="#8a1c1c",
                text=f"{badge.name} — nothing parsed. The requirements may be "
                     f"loaded by JavaScript; save the page from a browser and "
                     f"use File > Open saved badge page.")
        self.book.select(1)

    def _log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain(self) -> None:
        try:
            while True:
                msg = self.worker.queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _handle(self, msg: Message) -> None:
        if msg.kind == "catalog":
            self.catalog = list(msg.payload)
            self._filter()
            eagle = sum(1 for e in self.catalog if e.eagle_required)
            self.var_status.set(
                f"{len(self.catalog)} merit badges ({eagle} Eagle-required).")
        elif msg.kind == "preview":
            self._show_preview(msg.payload)
            self.var_status.set(f"Previewing {msg.payload.name}.")
        elif msg.kind == "log":
            self._log(str(msg.payload))
        elif msg.kind == "progress":
            self.progress.configure(value=float(msg.payload))
        elif msg.kind == "error":
            self.var_status.set(str(msg.payload))
            self._log(f"! {msg.payload}")
            messagebox.showerror("Something went wrong", str(msg.payload))
        elif msg.kind == "done":
            self.progress.stop()
            if self.progress.cget("mode") == "indeterminate":
                self.progress.configure(mode="determinate", value=0)
            if self.var_status.get().endswith("…"):
                self.var_status.set("Ready.")
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        workbook = self.var_style.get() == "workbook"
        self.spin_lines.configure(state="normal" if workbook else "disabled")
        has_selection = bool(self.tree.selection())
        self.btn_preview.configure(
            state="normal" if has_selection else "disabled")
        self.btn_generate.configure(
            state="normal" if has_selection or self.preview_badge else "disabled")

    # ------------------------------------------------------------- settings

    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, var in self._setting_vars().items():
            if key in data:
                try:
                    var.set(data[key])
                except tk.TclError:
                    pass

    def save_settings(self) -> None:
        data = {k: v.get() for k, v in self._setting_vars().items()}
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _setting_vars(self) -> dict[str, tk.Variable]:
        return {
            "format": self.var_format,
            "style": self.var_style,
            "note_lines": self.var_note_lines,
            "signoff": self.var_signoff,
            "resources": self.var_resources,
            "counselor": self.var_counselor,
            "unit": self.var_unit,
            "outdir": self.var_outdir,
            "eagle_only": self.var_eagle_only,
        }


def main(argv: list[str] | None = None) -> int:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.save_settings(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
