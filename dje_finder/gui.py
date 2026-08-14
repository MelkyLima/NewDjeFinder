import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import customtkinter as ctk

if os.name == "nt":
    import ctypes
from dje_finder.config import APP_NAME, logger
from dje_finder.persistence import IndexManager, StateManager
from dje_finder.search import (
    MATCH_ALL_TERMS,
    MATCH_EXACT_PHRASE,
    MATCH_NEAR_CONTEXT,
    PDFSearchEngine,
    SORT_NEWEST,
    SORT_OLDEST,
    SORT_RELEVANCE,
)
from dje_finder.worker import WorkerController


def _ctk_config(self, *args, **kwargs):
    if "foreground" in kwargs:
        kwargs["text_color"] = kwargs.pop("foreground")
    return self.configure(*args, **kwargs)


for _widget_class in (
    ctk.CTkButton,
    ctk.CTkComboBox,
    ctk.CTkEntry,
    ctk.CTkFrame,
    ctk.CTkLabel,
    ctk.CTkProgressBar,
):
    _widget_class.config = _ctk_config


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.window = None
        self.after_id = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, _event=None):
        self.after_id = self.widget.after(350, self.show)

    def show(self):
        self.after_id = None
        if self.window is not None:
            return

        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{self.widget.winfo_rootx() + self.widget.winfo_width() + 8}+{self.widget.winfo_rooty() + 8}")
        tk.Label(
            self.window,
            text=self.text,
            bg="#242d3f",
            fg="#f8fafc",
            font=("Segoe UI Semibold", 11),
            padx=10,
            pady=6,
        ).pack()

    def hide(self, _event=None):
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class TJRRSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.apply_window_chrome()
        self.root.after(250, self.apply_window_chrome)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.gui_queue = queue.Queue()
        self.index_mgr = IndexManager()
        self.state_mgr = StateManager()
        self.worker = WorkerController(self.index_mgr, self.state_mgr, self.gui_queue)
        self.search_engine = PDFSearchEngine()
        self.initializing = True
        self.indexing_in_progress = False
        self.search_in_progress = False
        self.search_offset = 0
        self.search_query = ""
        self.search_response = None
        self.search_rows = {}
        self.search_request_id = 0
        
        self.last_bytes = 0
        self.last_processed_dates = 0
        self.last_time = time.time()
        
        self.setup_ui()
        self.check_initial_state()
        self.root.after(100, self.prepare_initial_queue)
        self.process_queue()
        self.update_speed_label()
 
    def setup_ui(self):
        self.configure_modern_theme()
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        shell_frame = ctk.CTkFrame(self.root, fg_color=self.colors["window"], corner_radius=0)
        shell_frame.pack(fill=tk.BOTH, expand=True)

        sidebar = ctk.CTkFrame(shell_frame, width=88, fg_color=self.colors["sidebar"], corner_radius=0)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0), pady=0)
        sidebar.pack_propagate(False)

        brand_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand_frame.pack(fill=tk.X, padx=16, pady=(18, 28))
        ctk.CTkLabel(
            brand_frame,
            text="DJE",
            width=44,
            height=34,
            corner_radius=10,
            fg_color=self.colors["accent"],
            text_color="#ffffff",
            font=(self.font_family, 13, "bold"),
        ).pack(anchor=tk.CENTER)

        self.nav_buttons = {}
        self.create_nav_button(sidebar, "sync", "\ue72c", "Sincronização").pack(fill=tk.X, padx=10, pady=(0, 8))
        self.create_nav_button(sidebar, "search", "\ue721", "Busca textual").pack(fill=tk.X, padx=10, pady=(0, 8))

        ctk.CTkFrame(sidebar, fg_color="transparent").pack(fill=tk.BOTH, expand=True)

        content_frame = ctk.CTkFrame(shell_frame, fg_color=self.colors["window"], corner_radius=0)
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=22, pady=(20, 22))

        self.page_title = ctk.CTkLabel(content_frame, text="", text_color="#ffffff", font=(self.font_family, 24, "bold"))
        self.page_title.pack(anchor=tk.W, pady=(0, 4))
        self.page_subtitle = ctk.CTkLabel(content_frame, text="", text_color=self.colors["muted"], font=(self.font_family, 12))
        self.page_subtitle.pack(anchor=tk.W, pady=(0, 18))

        page_host = ctk.CTkFrame(content_frame, fg_color="transparent", corner_radius=0)
        page_host.pack(fill=tk.BOTH, expand=True)

        main_frame = ctk.CTkFrame(
            page_host,
            fg_color=self.colors["surface"],
            corner_radius=18,
            border_width=1,
            border_color=self.colors["border"],
        )
        search_frame = ctk.CTkFrame(
            page_host,
            fg_color=self.colors["surface"],
            corner_radius=18,
            border_width=1,
            border_color=self.colors["border"],
        )
        self.pages = {
            "sync": main_frame,
            "search": search_frame,
        }
        
        self.btn_action = ctk.CTkButton(
            main_frame,
            text="ATUALIZAR Base de PDFs",
            command=self.toggle_action,
            corner_radius=12,
            height=44,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            font=(self.font_family, 12, "bold"),
        )
        self.btn_action.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=(10, 22))
        
        self.lbl_erro = ctk.CTkLabel(main_frame, text="", text_color=self.colors["error"], wraplength=900, font=(self.font_family, 12))
        self.lbl_erro.pack(side=tk.BOTTOM, fill=tk.X, padx=22)
        
        self.lbl_pdf_atual = ctk.CTkLabel(
            main_frame,
            text="PDF atual: Aguardando...",
            text_color=self.colors["text"],
            font=(self.font_family, 12, "bold"),
        )
        self.lbl_pdf_atual.pack(anchor=tk.W, padx=22, pady=(22, 14))
        
        self.progress_var = tk.DoubleVar()
        self.progress_var.trace_add("write", self.update_progress_bar)
        self.progress_bar = ctk.CTkProgressBar(
            main_frame,
            height=12,
            corner_radius=6,
            fg_color="#111827",
            progress_color=self.colors["accent"],
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(fill=tk.X, padx=22, pady=(0, 5))
        
        self.lbl_pct = ctk.CTkLabel(main_frame, text="0.00%", text_color=self.colors["muted"], font=(self.font_family, 12))
        self.lbl_pct.pack(anchor=tk.E, padx=22, pady=(0, 15))
        
        info_frame = ctk.CTkFrame(
            main_frame,
            fg_color=self.colors["surface_alt"],
            corner_radius=16,
            border_width=1,
            border_color=self.colors["border"],
        )
        info_frame.pack(fill=tk.X, padx=22, pady=(0, 12))
        ctk.CTkLabel(
            info_frame,
            text="Estatísticas",
            text_color=self.colors["text"],
            font=(self.font_family, 12, "bold"),
        ).pack(anchor=tk.W, padx=16, pady=(14, 8))
        
        self.lbl_localizados = ctk.CTkLabel(info_frame, text="PDFs Totais localizados: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_localizados.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_atualizaveis = ctk.CTkLabel(info_frame, text="Datas pendentes de verificação: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_atualizaveis.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_baixados = ctk.CTkLabel(info_frame, text="PDFs Totais baixados: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_baixados.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_progresso = ctk.CTkLabel(info_frame, text="PDFs em progresso: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_progresso.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_fila = ctk.CTkLabel(info_frame, text="PDFs na fila: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_fila.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_velocidade_real = ctk.CTkLabel(info_frame, text="Velocidade de download: 0 KB/s", text_color=self.colors["muted"], font=(self.font_family, 12))
        self.lbl_velocidade_real.pack(anchor=tk.W, padx=16, pady=(2, 14))
        
        indexer_frame = ctk.CTkFrame(
            main_frame,
            fg_color=self.colors["surface_alt"],
            corner_radius=16,
            border_width=1,
            border_color=self.colors["border"],
        )
        indexer_frame.pack(fill=tk.X, padx=22, pady=(0, 12))
        ctk.CTkLabel(
            indexer_frame,
            text="Busca Textual (Conteúdo)",
            text_color=self.colors["text"],
            font=(self.font_family, 12, "bold"),
        ).pack(anchor=tk.W, padx=16, pady=(14, 8))
        
        self.lbl_indexados = ctk.CTkLabel(indexer_frame, text="PDFs Indexados para busca: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_indexados.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_paginas_indexadas = ctk.CTkLabel(indexer_frame, text="Total de documentos indexados: 0", text_color=self.colors["text"], font=(self.font_family, 12))
        self.lbl_paginas_indexadas.pack(anchor=tk.W, padx=16, pady=2)
        
        self.lbl_status_indexador = ctk.CTkLabel(indexer_frame, text="Status do buscador: Aguardando...", text_color=self.colors["muted"], font=(self.font_family, 12))
        self.lbl_status_indexador.pack(anchor=tk.W, padx=16, pady=(2, 14))
        
        speed_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        speed_frame.pack(fill=tk.X, padx=22, pady=(0, 10))
        ctk.CTkLabel(speed_frame, text="Modo:", text_color=self.colors["text"], font=(self.font_family, 12)).pack(side=tk.LEFT, padx=(0, 10))
        self.cb_speed = ctk.CTkComboBox(
            speed_frame,
            values=["1 - Lento (1MB/s)", "2 - Rápido (5MB/s)", "3 - Turbo (Ilimitado)"],
            state="readonly",
            corner_radius=10,
            fg_color="#111827",
            border_color=self.colors["border"],
            button_color=self.colors["surface_alt"],
            button_hover_color=self.colors["nav_selected"],
            dropdown_fg_color="#111827",
            dropdown_hover_color=self.colors["nav_selected"],
            dropdown_text_color=self.colors["text"],
            text_color=self.colors["text"],
            font=(self.font_family, 12),
            dropdown_font=(self.font_family, 12),
        )
        self.cb_speed.set("2 - Rápido (5MB/s)")
        self.cb_speed.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.setup_search_ui(search_frame)
        self.show_page("sync")

    def apply_window_chrome(self):
        if os.name != "nt":
            return

        try:
            self.root.update_idletasks()
            hwnd = self.root.winfo_id()

            dark_mode = ctypes.c_int(1)
            rounded = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        except Exception:
            pass

    def get_modern_font_family(self):
        available_fonts = set(tkfont.families(self.root))
        # A variante semibold mantém os textos nítidos e mais estáveis em telas Windows.
        if "Segoe UI Semibold" in available_fonts:
            return "Segoe UI Semibold"
        if "Segoe UI Variable Text Semibold" in available_fonts:
            return "Segoe UI Variable Text Semibold"
        return "Segoe UI"

    def create_nav_button(self, parent, page, icon, tooltip):
        button = ctk.CTkButton(
            parent,
            text=icon,
            anchor="center",
            height=48,
            corner_radius=12,
            fg_color="transparent",
            hover_color=self.colors["nav_hover"],
            text_color=self.colors["sidebar_text"],
            cursor="hand2",
            font=(self.icon_font_family, 21),
            command=lambda: self.show_page(page),
        )
        Tooltip(button, tooltip)
        self.nav_buttons[page] = button
        return button

    def create_combo(self, parent, variable, values, width, command):
        return ctk.CTkComboBox(
            parent,
            variable=variable,
            values=values,
            width=width,
            height=32,
            state="readonly",
            command=command,
            corner_radius=10,
            fg_color="#111827",
            border_color=self.colors["border"],
            button_color=self.colors["surface_alt"],
            button_hover_color=self.colors["nav_selected"],
            dropdown_fg_color="#111827",
            dropdown_hover_color=self.colors["nav_selected"],
            dropdown_text_color=self.colors["text"],
            text_color=self.colors["text"],
            font=(self.font_family, 12),
            dropdown_font=(self.font_family, 12),
        )

    def update_progress_bar(self, *_args):
        if hasattr(self, "progress_bar"):
            self.progress_bar.set(self.progress_var.get() / 100.0)

    def show_page(self, page):
        titles = {
            "sync": ("Sincronização", "Atualize a base local de PDFs e acompanhe a indexação."),
            "search": ("Busca textual", "Pesquise termos nos documentos indexados."),
        }
        for page_name, frame in self.pages.items():
            if page_name == page:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

        for page_name, button in self.nav_buttons.items():
            selected = page_name == page
            button.configure(
                fg_color=self.colors["nav_selected"] if selected else "transparent",
                text_color="#ffffff" if selected else self.colors["sidebar_text"],
            )

        title, subtitle = titles[page]
        self.page_title.config(text=title)
        self.page_subtitle.config(text=subtitle)
        if page == "search":
            self.entry_search.config(state="normal")
            self.root.after(50, self.entry_search.focus_set)

    def configure_modern_theme(self):
        self.colors = {
            "window": "#09111f",
            "sidebar": "#0f1724",
            "nav_hover": "#1f2a3a",
            "nav_selected": "#2b3b59",
            "sidebar_text": "#d7deea",
            "surface": "#1b2331",
            "surface_alt": "#242d3f",
            "border": "#3a465a",
            "text": "#f8fafc",
            "muted": "#a7b1c2",
            "accent": "#3b82f6",
            "accent_hover": "#60a5fa",
            "accent_pressed": "#2563eb",
            "error": "#f87171",
            "warning": "#fbbf24",
            "selection": "#34445e",
        }

        self.root.configure(bg=self.colors["window"])
        self.font_family = self.get_modern_font_family()
        self.icon_font_family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in tkfont.families(self.root) else "Segoe UI Symbol"
        self.root.option_add("*Font", f"{{{self.font_family}}} 12")
        tkfont.nametofont("TkDefaultFont").configure(family=self.font_family, size=12)
        tkfont.nametofont("TkTextFont").configure(family=self.font_family, size=12)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=(self.font_family, 12), background=self.colors["window"], foreground=self.colors["text"])
        style.configure("App.TFrame", background=self.colors["window"])
        style.configure("Sidebar.TFrame", background=self.colors["sidebar"])
        style.configure("TFrame", background=self.colors["window"])
        style.configure("Surface.TFrame", background=self.colors["surface"])
        style.configure("TLabel", background=self.colors["surface"], foreground=self.colors["text"])
        style.configure("Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"])
        style.configure("Title.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=(self.font_family, 14, "bold"))
        style.configure("Error.TLabel", background=self.colors["surface"], foreground=self.colors["error"])
        style.configure("Warning.TLabel", background=self.colors["surface"], foreground=self.colors["warning"])
        style.configure("Brand.TLabel", background=self.colors["sidebar"], foreground="#ffffff", font=(self.font_family, 16, "bold"))
        style.configure("BrandMark.TLabel", background=self.colors["accent"], foreground="#ffffff", font=(self.font_family, 12, "bold"), padding=(10, 6))
        style.configure("SidebarMuted.TLabel", background=self.colors["sidebar"], foreground="#7f8ba3", font=(self.font_family, 11))
        style.configure("PageTitle.TLabel", background=self.colors["window"], foreground="#ffffff", font=(self.font_family, 24, "bold"))
        style.configure("PageSubtitle.TLabel", background=self.colors["window"], foreground=self.colors["muted"], font=(self.font_family, 12))

        style.configure("TNotebook", background=self.colors["window"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            borderwidth=0,
            padding=(18, 10),
            font=(self.font_family, 12, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.colors["surface"]), ("active", self.colors["surface_alt"])],
            foreground=[("selected", self.colors["accent"]), ("active", self.colors["text"])],
        )

        style.configure(
            "Card.TLabelframe",
            background=self.colors["surface"],
            bordercolor=self.colors["border"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=(self.font_family, 12, "bold"),
        )

        style.configure(
            "TButton",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            focusthickness=0,
            focuscolor=self.colors["surface_alt"],
            padding=(14, 8),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", "#334155"), ("pressed", "#475569"), ("disabled", "#202938")],
            foreground=[("disabled", "#64748b")],
        )
        style.configure(
            "Accent.TButton",
            background=self.colors["accent"],
            foreground="#ffffff",
            bordercolor=self.colors["accent"],
            focuscolor=self.colors["accent"],
            font=(self.font_family, 12, "bold"),
            padding=(16, 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_pressed"]), ("disabled", "#1e3a8a")],
            foreground=[("disabled", "#bfdbfe")],
        )

        style.configure(
            "TEntry",
            fieldbackground="#111827",
            foreground=self.colors["text"],
            insertcolor=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            padding=(10, 7),
            relief="flat",
        )
        style.map("TEntry", bordercolor=[("focus", self.colors["accent"])])
        style.configure(
            "TCombobox",
            fieldbackground="#111827",
            background="#111827",
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            arrowcolor=self.colors["muted"],
            padding=(8, 6),
            relief="flat",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#111827")],
            bordercolor=[("focus", self.colors["accent"])],
            arrowcolor=[("active", self.colors["accent"])],
        )

        style.configure(
            "TProgressbar",
            background=self.colors["accent"],
            troughcolor="#111827",
            bordercolor="#111827",
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            thickness=12,
        )
        style.configure(
            "Treeview",
            background="#111827",
            fieldbackground="#111827",
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            rowheight=34,
            font=(self.font_family, 12),
        )
        style.configure(
            "Treeview.Heading",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            font=(self.font_family, 11, "bold"),
            padding=(8, 8),
        )
        style.map(
            "Treeview",
            background=[("selected", self.colors["selection"])],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure("Vertical.TScrollbar", background=self.colors["surface_alt"], troughcolor=self.colors["surface"], bordercolor=self.colors["border"])
        style.configure("Horizontal.TScrollbar", background=self.colors["surface_alt"], troughcolor=self.colors["surface"], bordercolor=self.colors["border"])
        self.root.option_add("*TCombobox*Listbox.background", "#111827")
        self.root.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.colors["nav_selected"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def setup_search_ui(self, parent):
        top_frame = ctk.CTkFrame(parent, fg_color="transparent")
        top_frame.pack(fill=tk.X, padx=22, pady=(22, 12))

        ctk.CTkLabel(top_frame, text="Termo:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 8))
        self.search_var = tk.StringVar()
        self.entry_search = ctk.CTkEntry(
            top_frame,
            textvariable=self.search_var,
            state="normal",
            corner_radius=10,
            height=38,
            fg_color="#111827",
            border_color=self.colors["border"],
            text_color=self.colors["text"],
        )
        self.entry_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_search.bind("<Return>", lambda _event: self.start_search(reset=True))
        self.entry_search.bind("<Button-1>", lambda _event: self.entry_search.focus_set())

        self.btn_search = ctk.CTkButton(
            top_frame,
            text="Buscar",
            command=lambda: self.start_search(reset=True),
            corner_radius=10,
            height=38,
            width=112,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            font=(self.font_family, 12, "bold"),
        )
        self.btn_search.pack(side=tk.LEFT)

        related_frame = ctk.CTkFrame(parent, fg_color="transparent")
        related_frame.pack(fill=tk.X, padx=22, pady=(0, 12))
        ctk.CTkLabel(related_frame, text="Perto de:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 8))
        self.search_related_var = tk.StringVar()
        self.entry_search_related = ctk.CTkEntry(
            related_frame,
            textvariable=self.search_related_var,
            state="normal",
            corner_radius=10,
            height=34,
            fg_color="#111827",
            border_color=self.colors["border"],
            text_color=self.colors["text"],
        )
        self.entry_search_related.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_search_related.bind("<Return>", lambda _event: self.start_search(reset=True))
        ctk.CTkLabel(related_frame, text="Distância:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 6))
        self.search_distance_var = tk.StringVar(value="50 palavras")
        self.cb_search_distance = self.create_combo(
            related_frame,
            variable=self.search_distance_var,
            values=["25 palavras", "50 palavras", "100 palavras", "200 palavras"],
            width=12,
            command=lambda _value: self.on_search_filter_changed(),
        )
        self.cb_search_distance.pack(side=tk.LEFT)

        filters_frame = ctk.CTkFrame(parent, fg_color="transparent")
        filters_frame.pack(fill=tk.X, padx=22, pady=(0, 12))

        ctk.CTkLabel(filters_frame, text="Ano:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 6))
        self.search_year_var = tk.StringVar(value="Todos")
        self.cb_search_year = self.create_combo(filters_frame, variable=self.search_year_var, values=["Todos"], width=116, command=lambda _value: self.on_search_filter_changed("year"))
        self.cb_search_year.pack(side=tk.LEFT, padx=(0, 12))

        ctk.CTkLabel(filters_frame, text="Mês:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 6))
        self.search_month_var = tk.StringVar(value="Todos")
        self.cb_search_month = self.create_combo(filters_frame, variable=self.search_month_var, values=["Todos"], width=116, command=lambda _value: self.on_search_filter_changed())
        self.cb_search_month.pack(side=tk.LEFT, padx=(0, 12))

        self._populate_initial_search_filters()

        ctk.CTkLabel(filters_frame, text="Modo:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 6))
        self.search_match_var = tk.StringVar(value="Todos os termos")
        self.cb_search_match = self.create_combo(
            filters_frame,
            variable=self.search_match_var,
            values=["Todos os termos", "Frase exata", "Contexto próximo"],
            width=150,
            command=lambda _value: self.on_search_filter_changed(),
        )
        self.cb_search_match.pack(side=tk.LEFT, padx=(0, 12))

        ctk.CTkLabel(filters_frame, text="Ordenar:", text_color=self.colors["text"]).pack(side=tk.LEFT, padx=(0, 6))
        self.search_sort_var = tk.StringVar(value="Relevância")
        self.cb_search_sort = self.create_combo(
            filters_frame,
            variable=self.search_sort_var,
            values=["Relevância", "Mais recentes", "Mais antigos"],
            width=150,
            command=lambda _value: self.on_search_filter_changed(),
        )
        self.cb_search_sort.pack(side=tk.LEFT, padx=(0, 12))

        self.btn_load_more = ctk.CTkButton(
            filters_frame,
            text="Carregar mais",
            command=lambda: self.start_search(reset=False),
            state="disabled",
            corner_radius=10,
            fg_color=self.colors["surface_alt"],
            hover_color=self.colors["nav_selected"],
        )
        self.btn_load_more.pack(side=tk.RIGHT)

        self.lbl_search_summary = ctk.CTkLabel(parent, text="Digite um termo para buscar nos PDFs indexados.", text_color=self.colors["muted"])
        self.lbl_search_summary.pack(fill=tk.X, padx=22, pady=(0, 4))

        self.lbl_search_warning = ctk.CTkLabel(parent, text="", text_color=self.colors["warning"], wraplength=920)
        self.lbl_search_warning.pack(fill=tk.X, padx=22, pady=(0, 8))

        table_frame = ctk.CTkFrame(
            parent,
            fg_color="#111827",
            corner_radius=16,
            border_width=1,
            border_color=self.colors["border"],
        )
        table_frame.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 0))

        columns = ("date", "period", "snippet", "path")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data")
        self.search_tree.heading("period", text="Ano/Mês")
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.heading("path", text="Arquivo")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("period", width=80, minwidth=70, stretch=False)
        self.search_tree.column("snippet", width=520, minwidth=260, stretch=True)
        self.search_tree.column("path", width=220, minwidth=120, stretch=True)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.search_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        actions_frame = ctk.CTkFrame(parent, fg_color="transparent")
        actions_frame.pack(fill=tk.X, padx=22, pady=(10, 22))
        self.btn_open_pdf = ctk.CTkButton(
            actions_frame,
            text="Abrir PDF",
            command=self.open_selected_pdf,
            corner_radius=10,
            fg_color=self.colors["surface_alt"],
            hover_color=self.colors["nav_selected"],
        )
        self.btn_open_pdf.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_open_folder = ctk.CTkButton(
            actions_frame,
            text="Abrir pasta",
            command=self.open_selected_folder,
            corner_radius=10,
            fg_color=self.colors["surface_alt"],
            hover_color=self.colors["nav_selected"],
        )
        self.btn_open_folder.pack(side=tk.LEFT)

    def start_search(self, reset=True):
        query = self.search_var.get().strip()
        if not reset and self.search_query:
            query = self.search_query
        if not query:
            self.lbl_search_summary.config(text="Digite um termo para iniciar a busca.")
            self.lbl_search_warning.config(text="")
            return
        if self.search_in_progress:
            return

        if reset:
            self.search_offset = 0
            self.search_query = query
            self.search_rows = {}
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
        elif self.search_response:
            self.search_offset = self.search_response.offset + len(self.search_response.results)
            self.search_query = query

        year = self._selected_filter_value(self.search_year_var.get(), 4)
        month = self._selected_filter_value(self.search_month_var.get(), 2)
        sort = self._selected_sort()
        match_mode = self._selected_match_mode()
        related_query = self.search_related_var.get().strip()
        context_distance = self._selected_context_distance()
        if related_query:
            match_mode = MATCH_NEAR_CONTEXT
        offset = self.search_offset
        self.search_in_progress = True
        self.search_request_id += 1
        request_id = self.search_request_id
        self.btn_search.config(state="disabled")
        self.btn_load_more.config(state="disabled")
        self.lbl_search_summary.config(text="Buscando...")
        self.lbl_search_warning.config(text="")

        threading.Thread(
            target=self._run_search,
            args=(request_id, query, year, month, sort, offset, match_mode, related_query, context_distance),
            daemon=True,
        ).start()

    def _populate_initial_search_filters(self):
        years = ["Todos"]
        months = ["Todos"]
        try:
            available_years = self.search_engine.get_available_years()
            if available_years:
                years.extend(available_years)
            selected_year = self.search_year_var.get()
            if selected_year != "Todos":
                available_months = self.search_engine.get_available_months(selected_year)
            else:
                available_months = self.search_engine.get_available_months()
            if available_months:
                months.extend(available_months)
        except Exception:
            available_years = []
            available_months = []

        self.cb_search_year.config(values=years)
        self.cb_search_month.config(values=months)
        self.search_year_var.set("Todos")
        self.search_month_var.set("Todos")

    def on_search_filter_changed(self, _event=None):
        if _event == "year" or (_event and getattr(_event, "widget", None) == self.cb_search_year):
            selected_year = self.search_year_var.get()
            try:
                if selected_year != "Todos":
                    available_months = self.search_engine.get_available_months(selected_year)
                else:
                    available_months = self.search_engine.get_available_months()
                month_values = ["Todos"] + (available_months or [])
                self.cb_search_month.config(values=month_values)
                if self.search_month_var.get() not in month_values:
                    self.search_month_var.set("Todos")
            except Exception:
                pass

        if self.search_var.get().strip() and not self.search_in_progress:
            self.start_search(reset=True)

    def _run_search(self, request_id, query, year, month, sort, offset, match_mode, related_query, context_distance):
        try:
            response = self.search_engine.search(
                query,
                year=year,
                month=month,
                sort=sort,
                offset=offset,
                match_mode=match_mode,
                related_query=related_query,
                context_distance=context_distance,
            )
            self.gui_queue.put({"type": "search_results", "request_id": request_id, "response": response})
        except Exception as error:
            logger.exception("Erro ao executar busca textual.")
            self.gui_queue.put({"type": "search_error", "request_id": request_id, "error": str(error)})

    def apply_search_results(self, response):
        self.search_response = response
        self.search_offset = response.offset
        for result in response.results:
            iid = result.date_str
            suffix = 1
            while iid in self.search_rows:
                suffix += 1
                iid = f"{result.date_str}-{suffix}"
            self.search_rows[iid] = result
            self.search_tree.insert(
                "",
                tk.END,
                iid=iid,
                tags=("even" if len(self.search_rows) % 2 == 0 else "odd",),
                values=(
                    result.display_date,
                    f"{result.year}/{result.month}",
                    result.snippet,
                    str(result.pdf_path),
                ),
            )

        visible = len(self.search_rows)
        if response.total == 0:
            self.lbl_search_summary.config(text="Nenhum resultado encontrado.")
        else:
            self.lbl_search_summary.config(text=f"Exibindo {visible} de {response.total} resultado(s).")

        if response.has_pending_indexing:
            pending = response.total_pdfs - response.indexed_pdfs
            self.lbl_search_warning.config(
                text=f"Aviso: ainda existem {pending} PDF(s) pendente(s) de indexação. A busca pode não cobrir toda a base."
            )
        else:
            self.lbl_search_warning.config(text="")

        self.btn_load_more.config(state="normal" if response.has_more else "disabled")
        self._refresh_filter_values(response)

    def apply_search_error(self, error):
        self.lbl_search_summary.config(text="Não foi possível concluir a busca.")
        self.lbl_search_warning.config(text=error)

    def finish_search_state(self):
        self.search_in_progress = False
        self.entry_search.config(state="normal")
        self.btn_search.config(state="normal")
        if self.search_response and self.search_response.has_more:
            self.btn_load_more.config(state="normal")

    def on_tab_changed(self, _event):
        self.show_page("search")

    def _refresh_filter_values(self, response):
        current_year = self.search_year_var.get()
        current_month = self.search_month_var.get()
        year_values = ["Todos"] + [f"{year} ({count})" for year, count in sorted(response.year_counts.items(), reverse=True)]
        month_values = ["Todos"] + [f"{month} ({count})" for month, count in sorted(response.month_counts.items())]
        self.cb_search_year.config(values=year_values)
        self.cb_search_month.config(values=month_values)
        current_year_value = self._selected_filter_value(current_year, 4)
        if current_year in year_values:
            self.search_year_var.set(current_year)
        elif current_year_value in response.year_counts:
            self.search_year_var.set(next(value for value in year_values if value.startswith(current_year_value)))
        else:
            self.search_year_var.set("Todos")
        current_month_value = self._selected_filter_value(current_month, 2)
        if current_month in month_values:
            self.search_month_var.set(current_month)
        elif current_month_value in response.month_counts:
            self.search_month_var.set(next(value for value in month_values if value.startswith(current_month_value)))
        else:
            self.search_month_var.set("Todos")

    def _selected_filter_value(self, value, size):
        if not value or value == "Todos":
            return None
        prefix = value.strip()[:size]
        return prefix if prefix.isdigit() else None

    def _selected_sort(self):
        label = self.search_sort_var.get()
        if label == "Mais recentes":
            return SORT_NEWEST
        if label == "Mais antigos":
            return SORT_OLDEST
        return SORT_RELEVANCE

    def _selected_match_mode(self):
        if self.search_match_var.get() == "Contexto próximo":
            return MATCH_NEAR_CONTEXT
        if self.search_match_var.get() == "Frase exata":
            return MATCH_EXACT_PHRASE
        return MATCH_ALL_TERMS

    def _selected_context_distance(self):
        value = self.search_distance_var.get().split(" ", 1)[0]
        try:
            return int(value)
        except ValueError:
            return 50

    def get_selected_search_result(self):
        selection = self.search_tree.selection()
        if not selection:
            messagebox.showinfo("Busca textual", "Selecione um resultado primeiro.")
            return None
        return self.search_rows.get(selection[0])

    def open_selected_pdf(self):
        result = self.get_selected_search_result()
        if result:
            self.open_path(result.pdf_path)

    def open_selected_folder(self):
        result = self.get_selected_search_result()
        if result:
            self.open_path(result.pdf_path.parent)

    def open_path(self, path):
        path = os.fspath(path)
        if not os.path.exists(path):
            messagebox.showwarning("Busca textual", "O arquivo ou pasta não existe mais no local esperado.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as error:
            messagebox.showerror("Busca textual", f"Não foi possível abrir o caminho:\n{error}")

    def check_initial_state(self):
        if self.state_mgr.has_valid_state():
            if messagebox.askyesno(
                "Retomar Sessão",
                "Existe uma sincronização interrompida.\n\n"
                "Sim: continua a fila salva e tenta novamente as falhas.\n"
                "Não: descarta a fila salva e recalcula a base a partir dos PDFs existentes.",
            ):
                self.state_mgr.load()
            else:
                self.state_mgr.clear()
        
        self.btn_action.config(text="Preparando base local...", state="disabled")
        self.cb_speed.config(state="disabled")
        self.lbl_pdf_atual.config(text="Preparando base local. Aguarde...")

    def prepare_initial_queue(self):
        threading.Thread(target=self.build_initial_queue, daemon=True).start()

    def build_initial_queue(self):
        try:
            self.worker.build_queue(self.report_initial_progress)
            self.gui_queue.put({"type": "initial_ready"})
        except Exception as error:
            logger.exception("Não foi possível preparar a base local.")
            self.gui_queue.put({"type": "initial_error", "error": str(error)})

    def report_initial_progress(self, phase, current, total, found):
        self.gui_queue.put({
            "type": "initial_progress",
            "phase": phase,
            "current": current,
            "total": total,
            "found": found,
        })

    def update_initial_progress(self, msg):
        phase = msg["phase"]
        current = msg["current"]
        total = msg["total"]
        found = msg["found"]

        if phase == "scan":
            percent = (current / total) * 100.0 if total else 100.0
            self.progress_var.set(min(max(percent, 0.0), 100.0))
            self.lbl_pct.config(text=f"{percent:.2f}%")
            self.lbl_pdf_atual.config(
                text=f"Preparando base local: analisando {current}/{total} arquivos..."
            )
            self.lbl_localizados.config(text=f"PDFs encontrados localmente: {found}")
            self.lbl_atualizaveis.config(text=f"Arquivos analisados: {current}/{total}")
            self.lbl_baixados.config(text=f"PDFs válidos importados: {found}")
            self.lbl_progresso.config(text="Etapa atual: varredura local")
            self.lbl_fila.config(text="Datas na fila: calculando...")
        elif phase == "gaps":
            self.progress_var.set(100.0)
            self.lbl_pct.config(text="100.00%")
            self.lbl_pdf_atual.config(text="Preparando base local: procurando lacunas no acervo...")
            self.lbl_localizados.config(text=f"PDFs encontrados localmente: {found}")
            self.lbl_atualizaveis.config(text=f"Datas em lacunas grandes: {current}")
            self.lbl_baixados.config(text=f"PDFs válidos importados: {found}")
            self.lbl_progresso.config(text="Etapa atual: conferência de lacunas")
            self.lbl_fila.config(text="Datas na fila: calculando...")

    def finish_initial_queue(self):
        self.initializing = False
        self.cb_speed.config(state="readonly")
        
        self.update_labels(
            pdf="",
            baixados=self.state_mgr.data.get("baixados", 0),
            localizados=self.state_mgr.data.get("localizados", 0),
            atualizaveis=self.state_mgr.data.get("atualizaveis", 0),
            em_progresso=0,
            restantes=len(self.state_mgr.data.get("fila_restante", []))
        )
        
        if self.state_mgr.data.get("atualizaveis", 0) == 0 and self.state_mgr.data.get("localizados", 0) > 0:
            self.btn_action.config(text="Rechecar Base", state="normal")
            self.lbl_pdf_atual.config(text=self.get_finished_text())
            self.progress_var.set(100.0)
            self.lbl_pct.config(text="100.00%")
        else:
            self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")
            self.lbl_pdf_atual.config(text="PDF atual: Aguardando...")
            
        self.worker.start_background_indexing()
        self.indexing_in_progress = True

    def fail_initial_queue(self, error):
        self.initializing = False
        self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")
        self.cb_speed.config(state="readonly")
        self.lbl_pdf_atual.config(text="Não foi possível preparar a base local.")
        self.lbl_erro.config(text=f"Erro ao preparar base local: {error}")

    def get_speed_config(self):
        return self.cb_speed.get()

    def toggle_action(self):
        if self.initializing:
            return
        txt = self.btn_action.cget("text")
        speed_cfg = self.get_speed_config()
        if txt in ("ATUALIZAR Base de PDFs", "Rechecar Base"):
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            
            if txt == "Rechecar Base":
                self.btn_action.config(text="Preparando...", state="disabled")
                self.lbl_pdf_atual.config(text="PDF atual: Rechecando base...")
                threading.Thread(target=self._rebuild_and_start, args=(speed_cfg,), daemon=True).start()
            else:
                self.worker.start(speed_cfg)
        elif txt == "Pausar":
            self.btn_action.config(text="Retomar")
            self.cb_speed.config(state="readonly")
            self.worker.pause()
        elif txt == "Retomar":
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            self.worker.resume(speed_cfg)

    def _rebuild_and_start(self, speed_cfg):
        try:
            self.worker.build_queue()
        except Exception as error:
            logger.exception("Não foi possível rechecar a base.")
            self.gui_queue.put({"type": "initial_error", "error": str(error)})
            return
        self.gui_queue.put({"type": "recheck_ready", "speed_cfg": speed_cfg})

    def get_finished_text(self):
        last_date = self.index_mgr.data.get("ultima_data_indexada", "")
        if last_date and len(last_date) == 8:
            return f"Base de Dados atualizada ({last_date[6:8]}/{last_date[4:6]}/{last_date[0:4]})"
        return "Base de Dados atualizada"

    def update_labels(self, pdf, baixados, localizados, atualizaveis, em_progresso, restantes):
        if pdf:
            self.lbl_pdf_atual.config(text=f"PDF atual: dpj-{pdf}.pdf")
            
        self.lbl_localizados.config(text=f"PDFs Totais localizados: {localizados}")
        self.lbl_atualizaveis.config(text=f"Datas pendentes de verificação: {atualizaveis}")
        self.lbl_baixados.config(text=f"PDFs Totais baixados: {baixados}")
        self.lbl_progresso.config(text=f"PDFs em progresso: {em_progresso}")
        self.lbl_fila.config(text=f"PDFs na fila: {restantes}")
        
        if localizados > 0:
            pct = (baixados / localizados) * 100.0
        else:
            pct = 100.0 if atualizaveis == 0 else 0.0
            
        pct = min(max(pct, 0.0), 100.0)
        self.progress_var.set(pct)
        self.lbl_pct.config(text=f"{pct:.2f}%")

    def process_queue(self):
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                if msg["type"] == "update":
                    self.update_labels(
                        msg["date"],
                        msg["baixados"],
                        msg["localizados"],
                        msg["atualizaveis"],
                        msg["em_progresso"],
                        msg["restantes"]
                    )
                    if msg["error"]:
                        self.lbl_erro.config(text=f"Último erro: {msg['error']}")
                elif msg["type"] == "checking_connection":
                    self.btn_action.config(text="Verificando...", state="disabled")
                    self.cb_speed.config(state="disabled")
                    self.lbl_pdf_atual.config(text="Verificando internet e portal...")
                    self.lbl_erro.config(text="")
                elif msg["type"] == "sync_started":
                    self.btn_action.config(text="Pausar", state="normal")
                    self.cb_speed.config(state="disabled")
                elif msg["type"] == "connection_error":
                    has_queue = len(self.state_mgr.data.get("fila_restante", [])) > 0 or len(self.state_mgr.data.get("em_andamento", [])) > 0
                    btn_text = "Retomar" if has_queue else "ATUALIZAR Base de PDFs"
                    self.btn_action.config(text=btn_text, state="normal")
                    self.cb_speed.config(state="readonly")
                    if msg["error_type"] == "internet":
                        msg_err = "Sem conexão ativa com a internet. A base local foi verificada, mas a sincronização online está pausada."
                    else:
                        msg_err = "Portal TJRR indisponível no momento. A base local foi verificada, mas a sincronização online está pausada."
                    if msg.get("error_detail"):
                        msg_err += f"\nDetalhes: {msg['error_detail']}"
                    self.lbl_pdf_atual.config(text="Sincronização online pausada.")
                    self.lbl_erro.config(text=msg_err)
                elif msg["type"] == "portal_unstable":
                    self.btn_action.config(text="Retomar", state="normal")
                    self.cb_speed.config(state="readonly")
                    msg_err = f"Portal TJRR apresentou instabilidade recente ({msg.get('error')}). A sincronização online foi pausada."
                    self.lbl_pdf_atual.config(text="Sincronização online pausada por instabilidade.")
                    self.lbl_erro.config(text=msg_err)
                elif msg["type"] == "done":
                    self.worker.finish()
                    self.btn_action.config(text="Rechecar Base", state="normal")
                    self.cb_speed.config(state="readonly")
                    self.lbl_pdf_atual.config(text=self.get_finished_text())
                    self.progress_var.set(100.0)
                    self.lbl_pct.config(text="100.00%")
                elif msg["type"] == "recheck_ready":
                    atualizaveis = self.state_mgr.data.get("atualizaveis", 0)
                    self.update_labels(
                        pdf="",
                        baixados=self.state_mgr.data.get("baixados", 0),
                        localizados=self.state_mgr.data.get("localizados", 0),
                        atualizaveis=atualizaveis,
                        em_progresso=0,
                        restantes=len(self.state_mgr.data.get("fila_restante", []))
                    )
                    if atualizaveis > 0:
                        self.btn_action.config(text="Pausar", state="normal")
                        self.worker.start(msg["speed_cfg"])
                    else:
                        self.btn_action.config(text="Rechecar Base", state="normal")
                        self.cb_speed.config(state="readonly")
                        self.lbl_pdf_atual.config(text=self.get_finished_text())
                        self.progress_var.set(100.0)
                        self.lbl_pct.config(text="100.00%")
                elif msg["type"] == "done_with_errors":
                    self.worker.finish(clear_state=False)
                    self.btn_action.config(text="Rechecar Base", state="normal")
                    self.cb_speed.config(state="readonly")
                    self.lbl_pdf_atual.config(text="PDF atual: Concluído com falhas.")
                    self.lbl_erro.config(
                        text="Algumas datas falharam. Clique em 'Rechecar Base' para tentar novamente."
                    )
                elif msg["type"] == "initial_progress":
                    self.update_initial_progress(msg)
                elif msg["type"] == "initial_ready":
                    self.finish_initial_queue()
                elif msg["type"] == "initial_error":
                    self.fail_initial_queue(msg["error"])
                elif msg["type"] == "index_progress":
                    current = msg["current"]
                    total = msg["total"]
                    last_date = msg["last_date"]
                    stats = msg["stats"]
                    eta_str = self.format_time(msg["eta"])
                    speed = msg["speed"]
                    self.lbl_indexados.config(
                        text=f"PDFs Indexados para busca: {stats['total_indexados']}/{stats['total_baixados']}"
                    )
                    self.lbl_paginas_indexadas.config(
                        text=f"Total de documentos indexados: {stats['total_paginas']}"
                    )
                    if total > 0:
                        if current == 0:
                            self.lbl_status_indexador.config(
                                text="Status: Iniciando indexação em segundo plano dos PDFs pendentes..."
                            )
                        else:
                            self.lbl_status_indexador.config(
                                text=f"Status: Indexando {current}/{total} ({speed:.1f} PDF/s) | ETA: {eta_str}"
                            )
                    else:
                        self.lbl_status_indexador.config(text="Status: Nenhum PDF pendente de indexação.")
                elif msg["type"] == "index_done":
                    stats = msg["stats"]
                    self.indexing_in_progress = False
                    self.lbl_indexados.config(
                        text=f"PDFs Indexados para busca: {stats['total_indexados']}/{stats['total_baixados']}"
                    )
                    self.lbl_paginas_indexadas.config(
                        text=f"Total de documentos indexados: {stats['total_paginas']}"
                    )
                    self.lbl_status_indexador.config(text="Status: Indexação em segundo plano concluída.")
                elif msg["type"] == "search_results":
                    if msg["request_id"] == self.search_request_id:
                        self.apply_search_results(msg["response"])
                        self.finish_search_state()
                elif msg["type"] == "search_error":
                    if msg["request_id"] == self.search_request_id:
                        self.apply_search_error(msg["error"])
                        self.finish_search_state()
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def update_speed_label(self):
        current_time = time.time()
        current_bytes = self.worker.total_bytes
        current_processed_dates = self.worker.processed_dates
        
        dt = current_time - self.last_time
        db = current_bytes - self.last_bytes
        processed_delta = current_processed_dates - self.last_processed_dates
        
        if dt > 0:
            speed = db / dt
            dates_per_second = processed_delta / dt
            if speed < 1024:
                txt = f"{speed:.1f} B/s"
            elif speed < 1024 * 1024:
                txt = f"{speed/1024:.1f} KB/s"
            else:
                txt = f"{speed/(1024*1024):.2f} MB/s"
            
            restantes = len(self.worker.fila) + len(self.worker.active_futures)
            if restantes > 0 and dates_per_second > 0:
                eta_sec = restantes / dates_per_second
                eta_str = self.format_time(eta_sec)
                eta_txt = f" | ETA: {eta_str}"
            elif restantes > 0:
                eta_txt = " | ETA: calculando..."
            else:
                eta_txt = ""

            self.lbl_velocidade_real.config(
                text=f"Download: {txt} | Consultas: {dates_per_second:.1f} datas/s{eta_txt}"
            )
            
        self.last_bytes = current_bytes
        self.last_processed_dates = current_processed_dates
        self.last_time = current_time
        self.root.after(1000, self.update_speed_label)

    def format_time(self, seconds):
        if seconds is None or seconds <= 0:
            return "calculando..."
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h:02d}h {m:02d}m {sec:02d}s"
        return f"{m:02d}m {sec:02d}s"

    def on_close(self):
        if self.indexing_in_progress:
            resposta = messagebox.askyesno(
                "Indexação em andamento",
                "A indexação de PDFs para busca textual ainda está em andamento.\n\n"
                "Se fechar agora, o processo será interrompido e retomado "
                "na próxima vez que o aplicativo for aberto.\n\n"
                "Deseja fechar mesmo assim?",
                icon="warning"
            )
            if not resposta:
                return  # Usuário escolheu não fechar

        # Para o download e sinaliza o indexador para interromper
        if self.worker.running:
            self.worker.stop()
        self.worker.stop_indexing()

        # Destrói a janela e encerra o processo por completo.
        # os._exit(0) é necessário porque ThreadPoolExecutor cria threads
        # não-daemon que manteriam o processo Python vivo após root.destroy().
        self.root.destroy()
        os._exit(0)
