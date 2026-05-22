from __future__ import annotations

from tkinter import Listbox, Text, Tk
from tkinter import ttk


UI_BG = "#f5f7fb"
UI_SURFACE = "#ffffff"
UI_SURFACE_MUTED = "#f8fafc"
UI_BORDER = "#d7dee8"
UI_TEXT = "#172033"
UI_MUTED_TEXT = "#5b667a"
UI_PRIMARY = "#2563eb"
UI_PRIMARY_HOVER = "#1d4ed8"
UI_READY = "#0f766e"
UI_WARNING = "#b45309"
UI_DANGER = "#b42318"
UI_PREVIEW_BG = "#111827"


def configure_app_style(root: Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    root.configure(background=UI_BG)
    style.configure(".", background=UI_BG, foreground=UI_TEXT, font=("", 9))
    style.configure("TFrame", background=UI_BG)
    style.configure("TLabel", background=UI_BG, foreground=UI_TEXT)
    style.configure("AppTitle.TLabel", font=("", 17, "bold"), foreground=UI_TEXT)
    style.configure("AppSummary.TLabel", foreground=UI_MUTED_TEXT)
    style.configure("NextAction.TLabel", background="#fff7ed", foreground="#9a3412", font=("", 10, "bold"))
    style.configure("StepStatus.TLabel", background="#e9f1ff", foreground="#1e3a8a", relief="flat")
    style.configure("SectionTitle.TLabel", font=("", 12, "bold"), foreground=UI_TEXT)
    style.configure("Hint.TLabel", foreground=UI_MUTED_TEXT)
    style.configure("Footer.TLabel", foreground=UI_MUTED_TEXT)
    style.configure("TNotebook", background=UI_BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 7), background="#e8edf5", foreground=UI_MUTED_TEXT)
    style.map(
        "TNotebook.Tab",
        background=[("selected", UI_SURFACE), ("active", "#f1f5f9")],
        foreground=[("selected", UI_PRIMARY), ("active", UI_TEXT)],
    )
    style.configure("TButton", padding=(10, 6), background=UI_SURFACE_MUTED, bordercolor=UI_BORDER, focusthickness=1)
    style.map("TButton", background=[("active", "#e8eef8")])
    style.configure(
        "Primary.TButton",
        font=("", 9, "bold"),
        foreground="#ffffff",
        background=UI_PRIMARY,
        bordercolor=UI_PRIMARY,
    )
    style.map(
        "Primary.TButton",
        foreground=[("disabled", "#dbeafe"), ("active", "#ffffff")],
        background=[("disabled", "#93c5fd"), ("active", UI_PRIMARY_HOVER)],
    )
    style.configure("TEntry", fieldbackground=UI_SURFACE, bordercolor=UI_BORDER, lightcolor=UI_BORDER, darkcolor=UI_BORDER)
    style.configure("TCombobox", fieldbackground=UI_SURFACE, bordercolor=UI_BORDER)
    style.configure("TLabelframe", background=UI_SURFACE, bordercolor=UI_BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=UI_SURFACE, foreground=UI_TEXT, font=("", 10, "bold"))
    style.configure("Treeview", background=UI_SURFACE, fieldbackground=UI_SURFACE, foreground=UI_TEXT, rowheight=24, bordercolor=UI_BORDER)
    style.configure("Treeview.Heading", background="#eef2f7", foreground=UI_TEXT, font=("", 9, "bold"))
    style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", UI_TEXT)])


def style_listbox(listbox: Listbox) -> None:
    listbox.configure(
        background=UI_SURFACE,
        foreground=UI_TEXT,
        selectbackground="#dbeafe",
        selectforeground=UI_TEXT,
        highlightthickness=1,
        highlightbackground=UI_BORDER,
        highlightcolor=UI_PRIMARY,
        borderwidth=0,
        relief="flat",
        activestyle="none",
    )


def style_text(text: Text) -> None:
    text.configure(
        background=UI_SURFACE,
        foreground=UI_TEXT,
        insertbackground=UI_TEXT,
        selectbackground="#dbeafe",
        selectforeground=UI_TEXT,
        highlightthickness=1,
        highlightbackground=UI_BORDER,
        highlightcolor=UI_PRIMARY,
        borderwidth=0,
        relief="flat",
    )
