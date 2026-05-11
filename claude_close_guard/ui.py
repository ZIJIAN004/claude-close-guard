"""Aggregate UI for multi-session close confirmation.

Dark, monospace, terminal-flavored — meant to feel like part of the same
PowerShell session Claude Code was running in. No ttk.Notebook chrome;
session switching is handled by a dropdown in the header (hidden when there's
only one session).
"""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field

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
    confirmed: bool
    selected: dict[int, list[MemoryCandidate]]


# Palette — matches a typical CC-in-PowerShell terminal look.
BG       = "#1e1e1e"   # window background
SURFACE  = "#252526"   # cards / inner panes
BORDER   = "#3c3c3c"   # subtle separators
TEXT     = "#e8e8e8"   # primary text
DIM      = "#9d9d9d"   # secondary text
MUTE     = "#6a6a6a"   # tertiary / placeholders
ACCENT   = "#d97757"   # Claude orange — headlines, primary button
INFO     = "#5fafef"   # type badges (user/feedback/project/reference)
WARN     = "#e5c07b"   # errors
BTN_BG   = "#2d2d2d"
BTN_BG_H = "#3a3a3a"


def _font(size: int, weight: str = "normal") -> tuple:
    families = tkfont.families()
    for name in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"):
        if name in families:
            return (name, size, weight)
    return ("TkFixedFont", size, weight)


def _flat_button(parent, text, command, primary=False):
    """Borderless tk.Button styled with hover state."""
    bg_fg = (ACCENT, BG) if primary else (BTN_BG, TEXT)
    bg, fg = bg_fg
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg,
        activebackground=BTN_BG_H if not primary else "#c66948",
        activeforeground=fg,
        bd=0, relief="flat", padx=14, pady=6,
        font=_font(10, "bold" if primary else "normal"),
        cursor="hand2",
    )
    if not primary:
        btn.bind("<Enter>", lambda e: btn.configure(bg=BTN_BG_H))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BTN_BG))
    return btn


_TYPE_COLORS = {
    "user":      "#5fafef",
    "feedback":  "#d97757",
    "project":   "#a3be8c",
    "reference": "#b48ead",
}


def show_aggregate_dialog(
    panels: list[SessionPanel],
    window_size: str = "780x600",
    post_close: bool = False,
) -> UIResult:
    """Block until the user clicks confirm or cancel. Mutates `panels` via polling."""
    root = tk.Tk()
    root.title("claude-close-guard")
    root.geometry(window_size)
    root.configure(bg=BG)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    state = {"confirmed": False, "done": False, "active": 0}

    # ── header ──────────────────────────────────────────────────────────────
    header = tk.Frame(root, bg=BG)
    header.pack(fill=tk.X, padx=18, pady=(14, 6))

    tk.Label(
        header, text="claude-close-guard",
        bg=BG, fg=MUTE, font=_font(9),
    ).pack(side="left")

    subtitle = "save memories" if post_close else "confirm close"
    tk.Label(
        header, text=f"  ·  {subtitle}",
        bg=BG, fg=MUTE, font=_font(9),
    ).pack(side="left")

    # ── session selector (only if >1) ───────────────────────────────────────
    selector_row = tk.Frame(root, bg=BG)
    selector_row.pack(fill=tk.X, padx=18, pady=(0, 4))

    active_label_var = tk.StringVar(value=panels[0].label if panels else "(no session)")
    tk.Label(
        selector_row, text="❯", bg=BG, fg=ACCENT, font=_font(13, "bold"),
    ).pack(side="left", padx=(0, 8))
    tk.Label(
        selector_row, textvariable=active_label_var,
        bg=BG, fg=TEXT, font=_font(11, "bold"),
    ).pack(side="left")

    if len(panels) > 1:
        position_var = tk.StringVar(value=f"1 / {len(panels)}")

        def select(idx: int) -> None:
            idx = idx % len(panels)
            state["active"] = idx
            active_label_var.set(panels[idx].label)
            position_var.set(f"{idx+1} / {len(panels)}")
            render_active()

        nav = tk.Frame(selector_row, bg=BG)
        nav.pack(side="right")
        _flat_button(nav, "◀", lambda: select(state["active"] - 1)).pack(side="left", padx=2)
        tk.Label(nav, textvariable=position_var, bg=BG, fg=MUTE,
                 font=_font(9), padx=8).pack(side="left")
        _flat_button(nav, "▶", lambda: select(state["active"] + 1)).pack(side="left", padx=2)

        def _pos_update() -> None:
            position_var.set(f"{state['active']+1} / {len(panels)}")
    else:
        def _pos_update() -> None:
            pass

    # subtle rule under header
    tk.Frame(root, bg=BORDER, height=1).pack(fill=tk.X, padx=18, pady=(2, 10))

    # ── body (single visible session at a time) ─────────────────────────────
    body = tk.Frame(root, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=18)

    # headline
    headline_var = tk.StringVar(value="summarizing…")
    headline_lbl = tk.Label(
        body, textvariable=headline_var,
        bg=BG, fg=ACCENT, font=_font(13, "bold"),
        wraplength=720, justify="left", anchor="w",
    )
    headline_lbl.pack(fill=tk.X, pady=(0, 8))

    # bullets
    bullets_frame = tk.Frame(body, bg=BG)
    bullets_frame.pack(fill=tk.X, pady=(0, 14))

    # separator before candidates
    tk.Frame(body, bg=BORDER, height=1).pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        body, text="memory candidates",
        bg=BG, fg=DIM, font=_font(9),
    ).pack(anchor="w", pady=(0, 6))

    # scrollable candidate list
    cands_outer = tk.Frame(body, bg=BG)
    cands_outer.pack(fill=tk.BOTH, expand=True)
    cands_canvas = tk.Canvas(cands_outer, bg=BG, highlightthickness=0, bd=0)
    cands_scroll = tk.Scrollbar(cands_outer, orient="vertical", command=cands_canvas.yview)
    cands_inner = tk.Frame(cands_canvas, bg=BG)
    cands_inner.bind(
        "<Configure>",
        lambda e: cands_canvas.configure(scrollregion=cands_canvas.bbox("all")),
    )
    inner_window = cands_canvas.create_window((0, 0), window=cands_inner, anchor="nw")
    cands_canvas.bind(
        "<Configure>",
        lambda e: cands_canvas.itemconfigure(inner_window, width=e.width),
    )
    cands_canvas.configure(yscrollcommand=cands_scroll.set)
    cands_canvas.pack(side="left", fill="both", expand=True)
    cands_scroll.pack(side="right", fill="y")

    def _on_wheel(e):
        cands_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    cands_canvas.bind_all("<MouseWheel>", _on_wheel)

    # Per-panel mutable cache so switching panels restores checkbox state.
    panel_state: list[dict] = [
        {"cand_vars": [], "rendered_for": None} for _ in panels
    ]

    def _clear_children(frame: tk.Frame) -> None:
        for w in frame.winfo_children():
            w.destroy()

    def render_active() -> None:
        idx = state["active"]
        _pos_update()
        if not panels:
            return
        panel = panels[idx]
        ps = panel_state[idx]

        _clear_children(bullets_frame)
        _clear_children(cands_inner)
        ps["cand_vars"] = []

        # error state
        if panel.error:
            headline_var.set("(failed)")
            headline_lbl.configure(fg=WARN)
            tk.Label(
                bullets_frame, text=panel.error,
                bg=BG, fg=DIM, font=_font(10),
                wraplength=720, justify="left", anchor="w",
            ).pack(anchor="w")
            ps["rendered_for"] = ("err", panel.error)
            return

        # loading state
        if panel.summary is None:
            headline_var.set("summarizing…")
            headline_lbl.configure(fg=DIM)
            tk.Label(
                bullets_frame, text="reading transcript and asking the model",
                bg=BG, fg=MUTE, font=_font(9),
                wraplength=720, justify="left", anchor="w",
            ).pack(anchor="w")
            ps["rendered_for"] = None
            return

        # populated
        s = panel.summary
        headline_var.set(s.headline or "(no headline)")
        headline_lbl.configure(fg=ACCENT)

        for b in s.bullets:
            row = tk.Frame(bullets_frame, bg=BG)
            row.pack(fill=tk.X, anchor="w", pady=1)
            tk.Label(row, text="─", bg=BG, fg=MUTE, font=_font(10)).pack(side="left", padx=(0, 8), anchor="n")
            tk.Label(
                row, text=b, bg=BG, fg=TEXT, font=_font(10),
                wraplength=680, justify="left", anchor="w",
            ).pack(side="left", fill="x", expand=True, anchor="w")

        if not s.candidates:
            tk.Label(
                cands_inner, text="(no memory candidates)",
                bg=BG, fg=MUTE, font=_font(9),
            ).pack(anchor="w", pady=4)
        else:
            for c in s.candidates:
                var = tk.BooleanVar(value=True)
                ps["cand_vars"].append(var)
                card = tk.Frame(cands_inner, bg=SURFACE)
                card.pack(fill="x", pady=4, padx=0)

                # row 1: checkbox + type badge + title
                top = tk.Frame(card, bg=SURFACE)
                top.pack(fill="x", padx=10, pady=(8, 2))
                tk.Checkbutton(
                    top, variable=var,
                    bg=SURFACE, activebackground=SURFACE,
                    fg=TEXT, selectcolor=SURFACE,
                    bd=0, highlightthickness=0,
                ).pack(side="left", padx=(0, 6))
                badge_color = _TYPE_COLORS.get(c.type, INFO)
                tk.Label(
                    top, text=c.type,
                    bg=SURFACE, fg=badge_color, font=_font(9, "bold"),
                ).pack(side="left", padx=(0, 10))
                tk.Label(
                    top, text=c.title,
                    bg=SURFACE, fg=TEXT, font=_font(10, "bold"),
                ).pack(side="left", anchor="w")

                # row 2: description
                tk.Label(
                    card, text=c.description,
                    bg=SURFACE, fg=DIM, font=_font(9),
                    wraplength=680, justify="left", anchor="w",
                ).pack(fill="x", padx=10, pady=(0, 2))

                # row 3: body preview
                body_preview = c.body if len(c.body) <= 280 else c.body[:280] + "…"
                tk.Label(
                    card, text=body_preview,
                    bg=SURFACE, fg=MUTE, font=_font(9),
                    wraplength=680, justify="left", anchor="w",
                ).pack(fill="x", padx=10, pady=(0, 8))

        ps["rendered_for"] = id(s)

    def poll() -> None:
        # re-render if active panel's summary/error changed
        idx = state["active"]
        if panels:
            panel = panels[idx]
            ps = panel_state[idx]
            current = ("err", panel.error) if panel.error else (id(panel.summary) if panel.summary else None)
            if ps["rendered_for"] != current:
                render_active()
        if not state["done"]:
            root.after(200, poll)

    # ── footer ──────────────────────────────────────────────────────────────
    tk.Frame(root, bg=BORDER, height=1).pack(fill=tk.X, padx=18, pady=(10, 0))
    footer = tk.Frame(root, bg=BG)
    footer.pack(fill=tk.X, padx=18, pady=12)

    def on_cancel():
        state["confirmed"] = False
        state["done"] = True
        root.destroy()

    def on_confirm():
        state["confirmed"] = True
        state["done"] = True
        root.destroy()

    if post_close:
        cancel_label = "skip"
        confirm_label = "save selected"
        cancel_action = lambda: (state.update(confirmed=True, done=True), root.destroy())
        hint = "window already closed"
    else:
        cancel_label = "cancel close"
        confirm_label = "save & close"
        cancel_action = on_cancel
        hint = "esc to cancel · enter to confirm"

    tk.Label(footer, text=hint, bg=BG, fg=MUTE, font=_font(9)).pack(side="left")
    _flat_button(footer, confirm_label, on_confirm, primary=True).pack(side="right", padx=(8, 0))
    _flat_button(footer, cancel_label, cancel_action).pack(side="right")

    # key bindings
    root.bind("<Escape>", lambda e: cancel_action())
    root.bind("<Return>", lambda e: on_confirm())

    # window-close protocol: in post-close, treat as confirm (window's gone anyway)
    root.protocol(
        "WM_DELETE_WINDOW",
        (lambda: (state.update(confirmed=True, done=True), root.destroy())) if post_close
        else on_cancel,
    )

    render_active()
    root.after(100, poll)
    root.mainloop()

    selected: dict[int, list[MemoryCandidate]] = {}
    if state["confirmed"]:
        for idx, panel in enumerate(panels):
            if panel.summary is None:
                selected[panel.pid] = []
                continue
            chosen = [
                c for var, c in zip(panel_state[idx]["cand_vars"], panel.summary.candidates)
                if var.get()
            ]
            selected[panel.pid] = chosen

    return UIResult(confirmed=state["confirmed"], selected=selected)


def run_summarizer_threads(
    panels: list[SessionPanel],
    summarize_one,
) -> list[threading.Thread]:
    """Kick off background summarization for every panel. Returns started threads."""
    threads: list[threading.Thread] = []
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
