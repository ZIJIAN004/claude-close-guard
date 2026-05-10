"""tkinter aggregate UI for multi-session close confirmation.

Layout:
    +-------------------------------------------------------+
    | claude-close-guard                                    |
    +------------+ -----------------------------------------+
    | Session A  |  Headline ......                         |
    | Session B  |  - bullet 1                              |
    | Session C  |  - bullet 2                              |
    |            |                                          |
    |            |  Memory candidates:                       |
    |            |   [x] feedback close-guard               |
    |            |       description ...                    |
    |            |   [ ] project xxx ...                    |
    +------------+ -----------------------------------------+
    | [Cancel close]                  [Confirm close + save]|
    +-------------------------------------------------------+
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import tkinter as tk
from tkinter import ttk

from .summarizer import MemoryCandidate, Summary


@dataclass
class SessionPanel:
    label: str
    pid: int
    summary: Summary | None = None
    error: str | None = None
    selected: dict[int, bool] = field(default_factory=dict)


@dataclass
class UIResult:
    confirmed: bool                      # True = close windows; False = cancel close
    selected: dict[int, list[MemoryCandidate]]  # pid -> chosen candidates


def show_aggregate_dialog(
    panels: list[SessionPanel],
    window_size: str = "780x560",
    post_close: bool = False,
) -> UIResult:
    """Block until the user clicks Confirm or Cancel.

    `panels` is mutated in place by background summarization; the UI polls.

    If `post_close=True`, the window has already been closed by the OS
    (X-button path). The Cancel button is hidden and Confirm just saves the
    selected memories.
    """
    root = tk.Tk()
    root.title(
        "claude-close-guard — save memories" if post_close
        else "claude-close-guard — confirm close"
    )
    root.geometry(window_size)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    state = {"confirmed": False, "done": False}

    main = ttk.Frame(root, padding=8)
    main.pack(fill=tk.BOTH, expand=True)

    notebook = ttk.Notebook(main)
    notebook.pack(fill=tk.BOTH, expand=True)

    tab_widgets: list[dict] = []
    for idx, panel in enumerate(panels):
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=panel.label)

        headline_var = tk.StringVar(value="Summarizing…")
        ttk.Label(frame, textvariable=headline_var, font=("Segoe UI", 11, "bold"),
                  wraplength=680, justify="left").pack(anchor="w", pady=(0, 4))

        bullets_text = tk.Text(frame, height=5, wrap="word", font=("Segoe UI", 10))
        bullets_text.pack(fill=tk.X, pady=(0, 6))
        bullets_text.insert("1.0", "(loading…)")
        bullets_text.config(state="disabled")

        ttk.Label(frame, text="Memory candidates (check the ones to save):",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cands_canvas = tk.Canvas(frame, highlightthickness=0)
        cands_scroll = ttk.Scrollbar(frame, orient="vertical", command=cands_canvas.yview)
        cands_inner = ttk.Frame(cands_canvas)
        cands_inner.bind(
            "<Configure>",
            lambda e, c=cands_canvas: c.configure(scrollregion=c.bbox("all")),
        )
        cands_canvas.create_window((0, 0), window=cands_inner, anchor="nw")
        cands_canvas.configure(yscrollcommand=cands_scroll.set)
        cands_canvas.pack(side="left", fill="both", expand=True)
        cands_scroll.pack(side="right", fill="y")

        tab_widgets.append({
            "panel": panel,
            "headline_var": headline_var,
            "bullets_text": bullets_text,
            "cands_inner": cands_inner,
            "cand_vars": [],
            "rendered": False,
        })

    def render_tab(tw: dict) -> None:
        if tw["rendered"]:
            return
        panel: SessionPanel = tw["panel"]
        if panel.error:
            tw["headline_var"].set(f"(failed) {panel.error[:200]}")
            tw["bullets_text"].config(state="normal")
            tw["bullets_text"].delete("1.0", tk.END)
            tw["bullets_text"].insert("1.0", panel.error)
            tw["bullets_text"].config(state="disabled")
            tw["rendered"] = True
            return
        if panel.summary is None:
            return
        s = panel.summary
        tw["headline_var"].set(s.headline or "(no headline)")
        tw["bullets_text"].config(state="normal")
        tw["bullets_text"].delete("1.0", tk.END)
        tw["bullets_text"].insert("1.0", "\n".join(f"• {b}" for b in s.bullets) or "(no bullets)")
        tw["bullets_text"].config(state="disabled")

        for i, c in enumerate(s.candidates):
            var = tk.BooleanVar(value=True)
            tw["cand_vars"].append(var)
            row = ttk.Frame(tw["cands_inner"])
            row.pack(fill="x", pady=2, anchor="w")
            ttk.Checkbutton(row, variable=var).pack(side="left", anchor="n")
            label_frame = ttk.Frame(row)
            label_frame.pack(side="left", fill="x", expand=True)
            ttk.Label(label_frame, text=f"[{c.type}] {c.title}", font=("Segoe UI", 10, "bold"),
                      wraplength=620, justify="left").pack(anchor="w")
            ttk.Label(label_frame, text=c.description, foreground="#555",
                      wraplength=620, justify="left").pack(anchor="w")
            body_preview = c.body if len(c.body) <= 240 else c.body[:240] + "…"
            ttk.Label(label_frame, text=body_preview, foreground="#777",
                      wraplength=620, justify="left", font=("Segoe UI", 9)).pack(anchor="w")
        if not s.candidates:
            ttk.Label(tw["cands_inner"], text="(no memory candidates suggested)",
                      foreground="#888").pack(anchor="w", pady=4)
        tw["rendered"] = True

    def poll() -> None:
        for tw in tab_widgets:
            render_tab(tw)
        if not state["done"]:
            root.after(200, poll)

    btn_frame = ttk.Frame(main)
    btn_frame.pack(fill=tk.X, pady=(8, 0))

    def on_cancel() -> None:
        state["confirmed"] = False
        state["done"] = True
        root.destroy()

    def on_confirm() -> None:
        state["confirmed"] = True
        state["done"] = True
        root.destroy()

    if not post_close:
        ttk.Button(btn_frame, text="Cancel close (keep windows open)",
                   command=on_cancel).pack(side="left")
        confirm_label = "Confirm close + save selected"
    else:
        ttk.Button(btn_frame, text="Skip (save nothing)",
                   command=lambda: (state.update(confirmed=True, done=True), root.destroy())).pack(side="left")
        confirm_label = "Save selected"
    ttk.Button(btn_frame, text=confirm_label, command=on_confirm).pack(side="right")

    # In post-close mode, closing the dialog should still mark "confirmed"
    # (window is already gone), it just won't save unticked items.
    root.protocol(
        "WM_DELETE_WINDOW",
        (lambda: (state.update(confirmed=True, done=True), root.destroy())) if post_close
        else on_cancel,
    )
    root.after(100, poll)
    root.mainloop()

    selected: dict[int, list[MemoryCandidate]] = {}
    if state["confirmed"]:
        for tw in tab_widgets:
            panel = tw["panel"]
            if panel.summary is None:
                selected[panel.pid] = []
                continue
            chosen = [
                c for var, c in zip(tw["cand_vars"], panel.summary.candidates)
                if var.get()
            ]
            selected[panel.pid] = chosen

    return UIResult(confirmed=state["confirmed"], selected=selected)


def run_summarizer_threads(
    panels: list[SessionPanel],
    summarize_one,  # callable: (panel) -> Summary
) -> list[threading.Thread]:
    """Kick off background summarization for every panel. Returns started threads."""
    threads = []
    for panel in panels:
        def worker(p=panel):
            try:
                p.summary = summarize_one(p)
            except Exception as exc:
                p.error = f"{type(exc).__name__}: {exc}"
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)
    return threads
